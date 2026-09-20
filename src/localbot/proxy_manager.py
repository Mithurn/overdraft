from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

import httpx

from localbot.config import LocalbotConfig
from localbot.litellm_builder import provider_runtime_env, write_litellm_config
from localbot.paths import GENERATED_DIR, LITELLM_CONFIG_PATH, PROXY_LOG_PATH, PROXY_PID_PATH
from localbot.tracker import init_db


def proxy_healthy(config: LocalbotConfig) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                f"http://{config.proxy.host}:{config.proxy.port}/health/liveliness"
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _read_pid() -> int | None:
    if not PROXY_PID_PATH.exists():
        return None
    try:
        return int(PROXY_PID_PATH.read_text().strip())
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _clear_pid() -> None:
    PROXY_PID_PATH.unlink(missing_ok=True)


def stop_proxy() -> bool:
    from localbot.paths import LAUNCHD_PLIST_PATH
    import os

    if LAUNCHD_PLIST_PATH.exists():
        import subprocess

        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(LAUNCHD_PLIST_PATH)],
            check=False,
        )
        return True

    pid = _read_pid()
    if pid is None:
        return False
    if _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.25)
    _clear_pid()
    return True


def _proxy_command(config: LocalbotConfig, master_key: str) -> list[str]:
    init_db()
    env_mode = config.proxy.mode
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    PROXY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if env_mode == "bridge":
        return [
            shutil.which("uvicorn") or "uvicorn",
            "localbot.bridge:app",
            "--host",
            config.proxy.host,
            "--port",
            str(config.proxy.port),
            "--log-level",
            "warning",
        ]

    write_litellm_config(config, master_key)
    litellm_bin = shutil.which("litellm")
    if not litellm_bin:
        raise SystemExit("litellm not found. Reinstall with: pip install -e .")
    return [
        litellm_bin,
        "--config",
        str(LITELLM_CONFIG_PATH),
        "--host",
        config.proxy.host,
        "--port",
        str(config.proxy.port),
    ]


def start_proxy_daemon(config: LocalbotConfig, master_key: str) -> None:
    env = os.environ.copy()
    env.update(provider_runtime_env(config))
    command = _proxy_command(config, master_key)

    with PROXY_LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    PROXY_PID_PATH.write_text(str(process.pid))


def ensure_proxy(config: LocalbotConfig, master_key: str, timeout_s: float | None = None) -> None:
    if timeout_s is None:
        timeout_s = 10.0 if config.proxy.mode == "bridge" else 45.0
    if proxy_healthy(config):
        return

    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        _wait_for_health(config, timeout_s)
        if proxy_healthy(config):
            return
        stop_proxy()

    start_proxy_daemon(config, master_key)
    _wait_for_health(config, timeout_s)
    if not proxy_healthy(config):
        raise SystemExit(
            f"Proxy failed to start. Check logs: {PROXY_LOG_PATH}"
        )


def _wait_for_health(config: LocalbotConfig, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    delay = 0.05
    while time.time() < deadline:
        if proxy_healthy(config):
            return
        time.sleep(delay)
        delay = min(delay * 1.5, 0.5)
