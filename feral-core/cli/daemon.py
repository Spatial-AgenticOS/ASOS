"""FERAL daemon management — generate launchd (macOS) or systemd (Linux) service files."""
import os
import sys
import platform
import shutil
from pathlib import Path


def install_service():
    """Generate and install a system service for FERAL Brain."""
    system = platform.system()
    feral_bin = shutil.which("feral") or sys.executable

    if system == "Darwin":
        _install_launchd(feral_bin)
    elif system == "Linux":
        _install_systemd(feral_bin)
    else:
        print(f"Daemon management not supported on {system}")
        return False
    return True


def _install_launchd(feral_bin: str):
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "ai.feral.brain.plist"

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.feral.brain</string>
    <key>ProgramArguments</key>
    <array>
        <string>{feral_bin}</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.feral/logs/brain.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.feral/logs/brain.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{os.path.dirname(feral_bin)}</string>
    </dict>
</dict>
</plist>"""

    (Path.home() / ".feral" / "logs").mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist)
    os.chmod(str(plist_path), 0o644)
    os.system(f"launchctl bootstrap gui/$(id -u) {plist_path}")
    print(f"Installed launchd service: {plist_path}")
    print("FERAL Brain will start automatically on login.")


def _install_systemd(feral_bin: str):
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "feral-brain.service"

    unit = f"""[Unit]
Description=FERAL Brain — AI Operating System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={feral_bin} serve
Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
KillMode=control-group
Environment=PATH=/usr/local/bin:/usr/bin:/bin:{os.path.dirname(feral_bin)}

[Install]
WantedBy=default.target
"""

    unit_path.write_text(unit)
    os.system("systemctl --user daemon-reload")
    os.system("systemctl --user enable feral-brain.service")
    os.system("systemctl --user start feral-brain.service")
    print(f"Installed systemd user service: {unit_path}")
    print("FERAL Brain will start automatically on login.")


def uninstall_service():
    """Remove the FERAL Brain system service."""
    system = platform.system()
    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "ai.feral.brain.plist"
        if plist_path.exists():
            os.system(f"launchctl bootout gui/$(id -u) {plist_path}")
            plist_path.unlink()
            print("Removed launchd service.")
    elif system == "Linux":
        os.system("systemctl --user stop feral-brain.service")
        os.system("systemctl --user disable feral-brain.service")
        unit_path = Path.home() / ".config" / "systemd" / "user" / "feral-brain.service"
        if unit_path.exists():
            unit_path.unlink()
            os.system("systemctl --user daemon-reload")
            print("Removed systemd service.")
