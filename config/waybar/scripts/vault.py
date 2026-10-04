#!/usr/bin/env python3
"""Waybar lock/unlock toggle for the Plasma Vault defined in plasmavaultrc.

With no argument, prints the vault's state as one JSON line. With "toggle",
asks for the password and mounts the vault, or unmounts it if it is open.

Only existing CryFS vaults are opened. CryFS runs non-interactively without
any --allow-* flag, so it refuses to create, upgrade, or accept a replaced
filesystem instead of changing the encrypted data.
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys
import tempfile
import time


CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
PLASMAVAULTRC = os.path.join(CONFIG_HOME, "plasmavaultrc")
CRYFS_ENV = {"CRYFS_FRONTEND": "noninteractive", "CRYFS_NO_UPDATE_CHECK": "true"}


def find_vault() -> dict[str, str] | None:
    """Return the first vault in plasmavaultrc, or None if there is none."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read(PLASMAVAULTRC, encoding="utf-8")
    except configparser.Error:
        return None
    for section in parser.sections():
        entry = parser[section]
        if section.startswith("/") and "mountPoint" in entry:
            return {
                "device": section,
                "mount_point": entry["mountPoint"],
                "name": entry.get("name", os.path.basename(section)),
                "backend": entry.get("backend", ""),
            }
    return None


def is_open(vault: dict[str, str]) -> bool:
    return os.path.ismount(vault["mount_point"])


def notify(summary: str, body: str = "") -> None:
    subprocess.run(["notify-send", "-a", "Vault", summary, body], check=False)


def status() -> int:
    vault = find_vault()
    if vault is None:
        print(json.dumps({"text": ""}), flush=True)
        return 0
    if is_open(vault):
        state, label = "unlocked", "OPEN"
        tip = f"{vault['name']} is unlocked at {vault['mount_point']}\nClick to lock, right-click to browse"
    else:
        state, label = "locked", "LOCK"
        tip = f"{vault['name']} is locked\nClick to unlock"
    print(json.dumps({
        "text": f"<span foreground='#c8c8c4'>VLT</span> <span weight='medium'>{label}</span>",
        "tooltip": tip,
        "class": state,
    }), flush=True)
    return 0


def ask_password(name: str) -> str | None:
    result = subprocess.run(
        ["zenity", "--password", f"--title=Unlock {name}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def unlock(vault: dict[str, str]) -> None:
    device, mount_point = vault["device"], vault["mount_point"]
    if vault["backend"] != "cryfs":
        notify("Vault not opened", f"Backend '{vault['backend']}' is not supported here.")
        return
    if not os.path.isfile(os.path.join(device, "cryfs.config")):
        notify("Vault not opened", f"No CryFS vault found at {device}.")
        return
    os.makedirs(mount_point, exist_ok=True)
    if os.listdir(mount_point):
        notify("Vault not opened", f"{mount_point} is not empty.")
        return

    password = ask_password(vault["name"])
    if not password:
        return

    # CryFS daemonizes after mounting and keeps its inherited stderr open, so
    # read errors from a file instead of a pipe that would never close.
    with tempfile.TemporaryFile(mode="w+") as errors:
        result = subprocess.run(
            ["cryfs", device, mount_point],
            input=password + "\n", text=True,
            stdout=subprocess.DEVNULL, stderr=errors,
            env={**os.environ, **CRYFS_ENV},
            start_new_session=True, check=False,
        )
        errors.seek(0)
        message = errors.read().strip().splitlines()

    if result.returncode != 0 or not is_open(vault):
        notify("Vault not opened", message[-1] if message else "Wrong password?")


def lock(vault: dict[str, str]) -> None:
    result = subprocess.run(
        ["cryfs-unmount", vault["mount_point"]],
        capture_output=True, text=True, check=False,
    )
    # cryfs-unmount can return before the FUSE mount is actually gone.
    for _ in range(30):
        if not is_open(vault):
            return
        time.sleep(0.1)
    if is_open(vault):
        detail = (result.stderr or result.stdout).strip()
        notify("Vault still open", detail or "Close any files or terminals using it, then try again.")


def toggle() -> int:
    vault = find_vault()
    if vault is None:
        notify("No vault configured", f"Nothing found in {PLASMAVAULTRC}.")
        return 1
    if is_open(vault):
        lock(vault)
    else:
        unlock(vault)
    return 0


def browse() -> int:
    vault = find_vault()
    if vault is not None and is_open(vault):
        subprocess.Popen(["xdg-open", vault["mount_point"]], start_new_session=True)
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "toggle":
        return toggle()
    if command == "browse":
        return browse()
    return status()


if __name__ == "__main__":
    sys.exit(main())
