from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
USER_CONFIG_DIR = Path.home() / ".config" / "localbot"
STATE_DIR = Path.home() / ".localbot"
GENERATED_DIR = STATE_DIR / "generated"
LITELLM_CONFIG_PATH = GENERATED_DIR / "litellm.config.yaml"
PROXY_PID_PATH = STATE_DIR / "proxy.pid"
PROXY_LOG_PATH = STATE_DIR / "proxy.log"
HANDOFF_LOG_PATH = STATE_DIR / "handoff.log"
LAUNCHD_LABEL = "com.localbot.proxy"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
SESSION_ID_PATH = STATE_DIR / "session.id"
USER_ENV_PATH = USER_CONFIG_DIR / ".env"
USER_CONFIG_PATH = USER_CONFIG_DIR / "localbot.yaml"
BUNDLED_EXAMPLE_PATH = PACKAGE_ROOT / "data" / "localbot.example.yaml"


def python_executable() -> str:
    return sys.executable


def config_candidates() -> list[Path]:
    return [
        USER_CONFIG_PATH,
        REPO_ROOT / "config" / "localbot.yaml",
    ]


def env_candidates() -> list[Path]:
    paths = [USER_ENV_PATH, REPO_ROOT / ".env"]
    return [path for path in paths if path.exists()]


def load_env_files() -> None:
    from dotenv import load_dotenv

    for path in env_candidates():
        load_dotenv(path, override=False)


def resolve_config_path(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return path

    if os.environ.get("LOCALBOT_CONFIG"):
        path = Path(os.environ["LOCALBOT_CONFIG"]).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return path

    for path in config_candidates():
        if path.exists():
            return path

    raise FileNotFoundError(
        "No config found. Run: cloudai setup"
    )


def example_config_path() -> Path:
    repo_example = REPO_ROOT / "config" / "localbot.example.yaml"
    if repo_example.exists():
        return repo_example
    if BUNDLED_EXAMPLE_PATH.exists():
        return BUNDLED_EXAMPLE_PATH
    raise FileNotFoundError("Missing bundled example config")
