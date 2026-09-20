from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

from localbot.paths import LAUNCHD_LABEL, LAUNCHD_PLIST_PATH, USER_CONFIG_DIR, python_executable


def install_service() -> None:
    python_bin = python_executable()
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    overdraft_script = _overdraft_script_path()
    target = local_bin / "overdraft"
    target.unlink(missing_ok=True)
    if overdraft_script:
        target.symlink_to(overdraft_script)
    else:
        target.write_text(
            "#!/bin/sh\n"
            f'exec "{python_bin}" -m localbot.cli "$@"\n'
        )
        target.chmod(0o755)

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [python_bin, "-m", "localbot.service"],
        "WorkingDirectory": str(USER_CONFIG_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(Path.home() / ".localbot" / "service.log"),
        "StandardErrorPath": str(Path.home() / ".localbot" / "service.log"),
    }
    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_PATH.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}", str(LAUNCHD_PLIST_PATH)], check=False)
    subprocess.run(["launchctl", "bootstrap", f"gui/{_uid()}", str(LAUNCHD_PLIST_PATH)], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{LAUNCHD_LABEL}"], check=False)
    print(f"Installed {target}")
    print(f"Background proxy enabled via {LAUNCHD_PLIST_PATH}")


def _overdraft_script_path() -> Path | None:
    found = shutil.which("overdraft")
    if found:
        return Path(found)
    repo_script = Path(__file__).resolve().parents[2] / "overdraft"
    if repo_script.exists():
        return repo_script
    return None


def _uid() -> int:
    import os

    return os.getuid()
