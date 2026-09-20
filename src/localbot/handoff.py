from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
import termios
import tty
from datetime import datetime, timezone
from pathlib import Path

from localbot.config import LocalbotConfig
from localbot.paths import HANDOFF_LOG_PATH
from localbot.session import latest_session_id
from localbot.session_export import export_handoff, archive_session

DEFAULT_LIMIT_PATTERNS = [
    r"usage limit",
    r"credit balance",
    r"rate limit",
    r"overloaded",
    r"429",
    r"quota",
    r"insufficient",
    r"billing",
]


def limit_patterns(config: LocalbotConfig) -> list[str]:
    if config.handoff.limit_patterns:
        return config.handoff.limit_patterns
    return DEFAULT_LIMIT_PATTERNS


def looks_like_limit_error(text: str, config: LocalbotConfig) -> bool:
    lowered = text.lower()
    for pattern in limit_patterns(config):
        if re.search(pattern, lowered):
            return True
    return False


def log_handoff(message: str) -> None:
    HANDOFF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with HANDOFF_LOG_PATH.open("a") as handle:
        handle.write(f"{stamp} {message}\n")


def proxy_claude_env(config: LocalbotConfig, master_key: str) -> dict[str, str]:
    base_url = f"http://{config.proxy.host}:{config.proxy.port}"
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_AUTH_TOKEN"] = master_key
    env.pop("ANTHROPIC_API_KEY", None)
    env["ANTHROPIC_MODEL"] = config.claude_code.default_model
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = config.claude_code.default_model
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = config.claude_code.subagent_model
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = config.claude_code.default_model
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = config.claude_code.subagent_model
    env["CLAUDE_CODE_EFFORT_LEVEL"] = config.claude_code.effort_level
    return env


def real_claude_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_BASE_URL", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def build_continue_command(session_id: str | None = None) -> list[str]:
    if session_id:
        return ["claude", "--resume", session_id]
    return ["claude", "--continue"]


def run_continue(config: LocalbotConfig, master_key: str, session_id: str | None = None) -> int:
    env = proxy_claude_env(config, master_key)
    command = build_continue_command(session_id or latest_session_id())
    if command[-1] == "--continue" and latest_session_id() is None:
        print("No Claude Code session found for this directory.")
        return 1
    print("Resumed on free backends (model quality may differ).")
    log_handoff(f"continue {' '.join(command)}")
    return subprocess.call(command, env=env)


def _relay_pty(master_fd: int, captured: list[str]) -> None:
    old_tty = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            readable, _, _ = select.select([master_fd, sys.stdin], [], [])
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                captured.append(text)
                os.write(sys.stdout.fileno(), chunk)
            if sys.stdin in readable:
                try:
                    chunk = os.read(sys.stdin.fileno(), 4096)
                except OSError:
                    break
                if not chunk:
                    break
                os.write(master_fd, chunk)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)


def run_smart_claude(
    config: LocalbotConfig,
    master_key: str,
    claude_args: list[str],
) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        from localbot.proxy_manager import ensure_proxy

        ensure_proxy(config, master_key)
        env = proxy_claude_env(config, master_key)
        command = ["claude", *claude_args]
        return subprocess.call(command, env=env)

    env = real_claude_env()
    command = ["claude", *claude_args]
    captured: list[str] = []

    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvpe(command[0], command, env)
        raise SystemExit(1)

    try:
        _relay_pty(master_fd, captured)
    finally:
        os.close(master_fd)
        _, status = os.waitpid(pid, 0)
    output = "".join(captured)
    if os.WIFEXITED(status):
        exit_code = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        exit_code = 128 + os.WTERMSIG(status)
    else:
        exit_code = 1

    if config.handoff.enabled and looks_like_limit_error(output, config):
        print("\ncloudai: Anthropic limit detected. Continuing on free backends…")
        log_handoff("smart auto-handoff triggered")
        from localbot.proxy_manager import ensure_proxy

        ensure_proxy(config, master_key)
        return run_prevhandoff(config, master_key)

    return exit_code


def run_prevhandoff(
    config: LocalbotConfig,
    master_key: str,
    session_id: str | None = None,
) -> int:
    from localbot.proxy_manager import ensure_proxy

    try:
        session, handoff_path = export_handoff(session_id=session_id)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    archive_session(session)
    ensure_proxy(config, master_key)
    env = proxy_claude_env(config, master_key)
    prompt = handoff_path.read_text()
    print(f"Handoff written to {handoff_path}")
    print("Starting fresh session on free backends…")
    log_handoff(f"prevhandoff {session.session_id} -> {handoff_path}")
    return subprocess.call(
        [
            "claude",
            "Continue this work from the handoff below. The previous session was archived.\n\n"
            + prompt,
        ],
        env=env,
    )
