#!/usr/bin/env python3
"""Pinned app launchers for Waybar image modules.

"icon <desktop-id>" prints the app's icon path and name for an image module.
"open <desktop-id>" focuses the app's most recent window, cycles to its next
window when one is already focused, or launches it when none is open.
"""

from __future__ import annotations

import configparser
import json
import os
import socket
import subprocess
import sys


ICON_SIZE = 32
ICON_EXTENSIONS = (".svg", ".png")


def data_dirs() -> list[str]:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [data_home, *[d for d in system.split(":") if d]]


def desktop_entry(desktop_id: str) -> configparser.SectionProxy | None:
    for base in data_dirs():
        path = os.path.join(base, "applications", desktop_id + ".desktop")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            if parser.read(path, encoding="utf-8") and parser.has_section("Desktop Entry"):
                return parser["Desktop Entry"]
        except configparser.Error:
            continue
    return None


def icon_theme() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(os.path.join(config_home, "gtk-3.0", "settings.ini"), encoding="utf-8")
        return parser.get("Settings", "gtk-icon-theme-name", fallback="hicolor")
    except configparser.Error:
        return "hicolor"


def theme_roots(theme: str) -> list[str]:
    bases = [os.path.expanduser("~/.icons")] + [os.path.join(d, "icons") for d in data_dirs()]
    return [os.path.join(base, theme) for base in bases if os.path.isdir(os.path.join(base, theme))]


def theme_chain(theme: str) -> list[str]:
    """The theme followed by everything it inherits, ending with hicolor."""
    chain, pending = [], [theme]
    while pending:
        name = pending.pop(0)
        if name in chain:
            continue
        chain.append(name)
        for root in theme_roots(name):
            index = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                index.read(os.path.join(root, "index.theme"), encoding="utf-8")
            except configparser.Error:
                continue
            inherits = index.get("Icon Theme", "Inherits", fallback="")
            pending.extend(n.strip() for n in inherits.split(",") if n.strip())
    if "hicolor" not in chain:
        chain.append("hicolor")
    return chain


def size_rank(directory: str) -> int:
    """Prefer scalable icons, then the smallest bitmap at least ICON_SIZE wide."""
    if "scalable" in directory:
        return 0
    for part in directory.split(os.sep):
        width = part.split("x", 1)[0].split("@", 1)[0]
        if width.isdigit():
            size = int(width)
            return 1 + (size - ICON_SIZE if size >= ICON_SIZE else 10_000 - size)
    return 20_000


def find_icon(name: str) -> str | None:
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    for theme in theme_chain(icon_theme()):
        found = []
        for root in theme_roots(theme):
            for directory, _, files in os.walk(root):
                for ext in ICON_EXTENSIONS:
                    if name + ext in files:
                        found.append(os.path.join(directory, name + ext))
        if found:
            return min(found, key=lambda path: size_rank(os.path.dirname(path)))
    for ext in ICON_EXTENSIONS:
        path = os.path.join("/usr/share/pixmaps", name + ext)
        if os.path.isfile(path):
            return path
    return None


def hypr_request(command: str) -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    path = os.path.join(runtime, "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        sock.sendall(command.encode())
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks).decode()


def app_windows(window_class: str) -> list[dict]:
    clients = json.loads(hypr_request("j/clients"))
    windows = [c for c in clients if c.get("class", "").lower() == window_class.lower() and c.get("mapped", True)]
    return sorted(windows, key=lambda c: c.get("focusHistoryID", 0))


def focus(address: str) -> None:
    lua = f"hl.dispatch(hl.dsp.focus({{ window = 'address:{address}' }}))"
    subprocess.run(["hyprctl", "eval", lua], stdout=subprocess.DEVNULL, check=False)


def icon(desktop_id: str) -> int:
    entry = desktop_entry(desktop_id)
    path = find_icon(entry.get("Icon", desktop_id)) if entry else None
    print(path or "")
    print(entry.get("Name", desktop_id) if entry else desktop_id)
    return 0


def open_app(desktop_id: str) -> int:
    entry = desktop_entry(desktop_id)
    window_class = entry.get("StartupWMClass", desktop_id) if entry else desktop_id
    windows = app_windows(window_class)
    if not windows:
        subprocess.Popen(["gtk-launch", desktop_id], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    # Already on this app: step to its least recently used window instead.
    target = windows[-1] if windows[0].get("focusHistoryID") == 0 and len(windows) > 1 else windows[0]
    focus(target["address"])
    return 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("icon", "open"):
        print("usage: pinned.py icon|open <desktop-id>", file=sys.stderr)
        return 2
    return icon(sys.argv[2]) if sys.argv[1] == "icon" else open_app(sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
