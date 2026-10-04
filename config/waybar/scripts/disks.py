#!/usr/bin/env python3
"""Waybar storage reading: root usage in the bar, every disk in the tooltip.

Prints one JSON line. Mounted block-device filesystems are read from
/proc/self/mountinfo; bind mounts, loop devices, and the boot partition
are left out so each disk shows once.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys


MOUNTINFO = "/proc/self/mountinfo"
SKIP_MOUNTS = {"/boot", "/efi", "/boot/efi"}
SKIP_FSTYPES = {"squashfs", "iso9660", "udf"}
WARN_PERCENT = 90
BAR_CELLS = 20

RED = "#cc1515"
MUTED = "#a29b96"
LABEL = "#c8c8c4"
TRACK = "#2a2a2a"


def unescape(field: str) -> str:
    """Decode mountinfo's octal escapes (\\040 is a space)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def mounted_disks() -> list[str]:
    """Return one mount point per block device, shortest path first."""
    by_device: dict[str, str] = {}
    try:
        with open(MOUNTINFO, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    for line in lines:
        head, _, tail = line.partition(" - ")
        fields, extra = head.split(), tail.split()
        if len(fields) < 5 or len(extra) < 2:
            continue
        device, root, mount = fields[2], unescape(fields[3]), unescape(fields[4])
        fstype, source = extra[0], extra[1]
        if root != "/" or not source.startswith("/dev/") or source.startswith("/dev/loop"):
            continue
        if fstype in SKIP_FSTYPES or mount in SKIP_MOUNTS:
            continue
        if device not in by_device or len(mount) < len(by_device[device]):
            by_device[device] = mount
    return sorted(by_device.values(), key=lambda m: (m != "/", m))


def usage(mount: str) -> tuple[int, int, int] | None:
    """Return (percent, used bytes, total bytes), with percent computed like df."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    if used + avail <= 0:
        return None
    percent = -(-used * 100 // (used + avail))
    return percent, used, st.f_blocks * st.f_frsize


def human(size: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.0f}{unit}" if size >= 10 or unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return ""


def bar(percent: int) -> str:
    filled = min(BAR_CELLS, round(percent * BAR_CELLS / 100))
    return (
        f"<span font_family='JetBrainsMono Nerd Font'>"
        f"<span foreground='{RED}'>{'━' * filled}</span>"
        f"<span foreground='{TRACK}'>{'━' * (BAR_CELLS - filled)}</span></span>"
    )


def render() -> dict[str, object]:
    readings = [(m, u) for m in mounted_disks() if (u := usage(m))]
    if not readings:
        return {"text": ""}
    width = max(len(m) for m, _ in readings)
    rows = [f"<span foreground='{RED}' weight='medium'>STORAGE</span>"]
    for mount, (percent, used, total) in readings:
        name = html.escape(mount.ljust(width))
        pct = f"{percent:>3}%"
        if percent >= WARN_PERCENT:
            pct = f"<span foreground='{RED}'>{pct}</span>"
        rows.append(f"{name}  {bar(percent)} {pct}")
        rows.append(
            f"<span foreground='{MUTED}' size='small'>{' ' * width}  "
            f"{human(used)} of {human(total)}</span>"
        )
    root = next((u for m, u in readings if m == "/"), readings[0][1])
    fullest = max(u[0] for _, u in readings)
    return {
        "text": (
            f"<span foreground='{LABEL}'>DSK</span> <span weight='medium'>{root[0]}</span>"
            f"<span foreground='{LABEL}'>%</span>"
        ),
        "tooltip": "\n".join(rows),
        "class": "warning" if fullest >= WARN_PERCENT else "",
    }


def main() -> int:
    print(json.dumps(render()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
