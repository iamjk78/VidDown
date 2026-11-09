"""Spouštění po přihlášení: LaunchAgent (macOS), registr Run (Windows), systemd --user (Linux)."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "cz.viddown.app"


def command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "serve"]
    return [sys.executable, "-m", "viddown", "serve"]


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _linux_unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "viddown.service"


def enable() -> str:
    cmd = command()
    if sys.platform == "darwin":
        p = _mac_plist()
        p.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k.startswith("VIDDOWN_")}
        env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin")
        if not getattr(sys, "frozen", False):
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        with open(p, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": cmd, "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
                           "EnvironmentVariables": env, "ProcessType": "Background"}, f)
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        subprocess.run(["launchctl", "load", str(p)], capture_output=True)
        return str(p)
    if sys.platform == "win32":
        import winreg
        exe = cmd[0].replace("python.exe", "pythonw.exe") if not getattr(sys, "frozen", False) else cmd[0]
        value = " ".join(f'"{c}"' for c in [exe, *cmd[1:]])
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "VidDown", 0, winreg.REG_SZ, value)
        return r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run\VidDown"
    p = _linux_unit()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[Unit]\nDescription=VidDown\nAfter=network-online.target\n\n[Service]\n"
                 f"ExecStart={' '.join(cmd)}\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "viddown.service"], capture_output=True)
    return str(p)


def disable() -> None:
    if sys.platform == "darwin":
        p = _mac_plist()
        if p.exists():
            subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
            p.unlink()
    elif sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "VidDown")
        except FileNotFoundError:
            pass
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", "viddown.service"], capture_output=True)
        _linux_unit().unlink(missing_ok=True)


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return _mac_plist().exists()
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "VidDown")
                return True
        except FileNotFoundError:
            return False
    return _linux_unit().exists()
