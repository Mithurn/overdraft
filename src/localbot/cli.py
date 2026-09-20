from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from localbot.config import load_config
from localbot.doctor import claude_version, format_doctor, run_doctor
from localbot.editor import (
    ensure_claude_editor_hook,
    format_open_label,
    open_in_editor,
    parse_location,
    search_repo,
)
from localbot.commands import ensure_prevhandoff_command
from localbot.handoff import run_continue, run_prevhandoff, run_smart_claude
from localbot.install import install_service
from localbot.litellm_builder import provider_runtime_env
from localbot.proxy_manager import _proxy_command, ensure_proxy, proxy_healthy, stop_proxy
from localbot.paths import (
    LITELLM_CONFIG_PATH,
    PROXY_LOG_PATH,
    REPO_ROOT,
    SESSION_ID_PATH,
    STATE_DIR,
    example_config_path,
    load_env_files,
    resolve_config_path,
)
from localbot.setup_wizard import run_setup
from localbot.usage import fetch_usage, format_usage


def _load_env() -> None:
    load_env_files()


def _master_key(config_path: Path | None = None) -> tuple[object, str]:
    config = load_config(resolve_config_path(config_path and str(config_path)))
    key = os.environ.get(config.proxy.master_key_env)
    if not key:
        raise SystemExit(
            f"Missing {config.proxy.master_key_env}. Run: overdraft setup"
        )
    return config, key


def cmd_setup(_: argparse.Namespace) -> None:
    run_setup()


def cmd_init(_: argparse.Namespace) -> None:
    target = REPO_ROOT / "config" / "localbot.yaml"
    example = example_config_path()
    if target.exists():
        print(f"Config already exists: {target}")
        return
    shutil.copy(example, target)
    print(f"Created {target}")
    print("For installed use, prefer: overdraft setup")


def cmd_doctor(args: argparse.Namespace) -> None:
    config, _ = _master_key(args.config)
    print(format_doctor(run_doctor(config)))
    version = claude_version()
    if version:
        print(f"  Claude Code: {version}")


def cmd_serve(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    env = os.environ.copy()
    env.update(provider_runtime_env(config))
    command = _proxy_command(config, master_key)

    print(f"Starting {config.proxy.mode} proxy on http://{config.proxy.host}:{config.proxy.port}")
    if config.proxy.mode == "litellm":
        print(f"LiteLLM config: {LITELLM_CONFIG_PATH}")
    print(f"Logs: {PROXY_LOG_PATH}")
    raise SystemExit(subprocess.call(command, env=env))


def cmd_install(_: argparse.Namespace) -> None:
    install_service()


def _claude_env(config, master_key: str) -> dict[str, str]:
    base_url = f"http://{config.proxy.host}:{config.proxy.port}"
    env = os.environ.copy()
    env.update(provider_runtime_env(config))
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


def _launch_claude(args: argparse.Namespace, config, master_key: str) -> int:
    if not shutil.which("claude"):
        raise SystemExit("claude CLI not found. Install Claude Code first.")

    env = _claude_env(config, master_key)
    command = ["claude", *getattr(args, "claude_args", [])]
    if getattr(args, "model", None):
        command.extend(["--model", args.model])
    return subprocess.call(command, env=env)


def _model_label(config, model_id: str) -> str:
    model = config.model_by_id(model_id)
    provider = config.provider_for_model(model_id)
    name = model.litellm_model.split("/", 1)[-1]
    return f"{provider.name}/{name}"


def _ensure_session_id() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SESSION_ID_PATH.exists() or not SESSION_ID_PATH.read_text().strip():
        SESSION_ID_PATH.write_text(uuid.uuid4().hex)


def _routing_lines(config) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    aliases = [
        config.claude_code.default_model,
        config.claude_code.subagent_model,
        *config.routing.claude_aliases,
    ]
    for alias in aliases:
        if alias in seen:
            continue
        seen.add(alias)
        model_id = config.routing.model_id_for_alias(alias)
        lines.append(f"  {alias} → {_model_label(config, model_id)}")
    if config.routing.fallbacks:
        chain = " → ".join(_model_label(config, model_id) for model_id in config.routing.fallbacks)
        lines.append(f"  (fallback chain: {chain})")
    return lines


def cmd_open(args: argparse.Namespace) -> None:
    try:
        location = parse_location(args.location)
        open_in_editor(location)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Opened {format_open_label(location)}")


def cmd_find(args: argparse.Namespace) -> None:
    try:
        hits = search_repo(args.pattern, glob=args.glob, limit=args.limit)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    if not hits:
        print("No matches.")
        raise SystemExit(1)

    for hit in hits:
        print(f"{hit.path}:{hit.line}: {hit.text}")

    if args.open:
        hit = hits[0]
        open_in_editor(parse_location(f"{hit.path}:{hit.line}"))
        print(f"Opened {hit.path}:{hit.line}")


def cmd_run(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    _ensure_session_id()
    if ensure_claude_editor_hook():
        print("Updated editor hook in CLAUDE.md", flush=True)
    if ensure_prevhandoff_command(Path.cwd()):
        print("Installed /prevhandoff command", flush=True)
    ensure_proxy(config, master_key)
    if not args.quiet:
        if os.environ.get("ANTHROPIC_API_KEY"):
            print("Mode: smart (Anthropic first, overdraft handoff on limit)", flush=True)
        else:
            print("Routing:", flush=True)
            for line in _routing_lines(config):
                print(line, flush=True)
    raise SystemExit(run_smart_claude(config, master_key, getattr(args, "claude_args", [])))


def cmd_smart(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    _ensure_session_id()
    ensure_proxy(config, master_key)
    raise SystemExit(run_smart_claude(config, master_key, getattr(args, "claude_args", [])))


def cmd_continue(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    ensure_proxy(config, master_key)
    raise SystemExit(run_continue(config, master_key, getattr(args, "session_id", None)))


def cmd_prevhandoff(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    raise SystemExit(run_prevhandoff(config, master_key, getattr(args, "session_id", None)))


def cmd_claude(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    if not proxy_healthy(config):
        raise SystemExit(
            "Proxy is not running. Use:\n"
            "  overdraft\n"
            "or:\n"
            "  overdraft run"
        )
    raise SystemExit(_launch_claude(args, config, master_key))


def cmd_stop(_: argparse.Namespace) -> None:
    if stop_proxy():
        print("Proxy stopped.")
    else:
        print("Proxy was not running.")


def cmd_restart(args: argparse.Namespace) -> None:
    stop_proxy()
    config, master_key = _master_key(args.config)
    ensure_proxy(config, master_key)
    print(f"Proxy restarted ({config.proxy.mode}).")


def cmd_usage(args: argparse.Namespace) -> None:
    config, master_key = _master_key(args.config)
    snapshot = fetch_usage(config, master_key)
    print(format_usage(snapshot, config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overdraft")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to localbot.yaml",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Start proxy and launch Claude Code on free backends")
    run_parser.add_argument("--model", help="Override Claude Code model alias")
    run_parser.add_argument("--quiet", action="store_true", help="Hide proxy startup message")
    run_parser.add_argument("claude_args", nargs=argparse.REMAINDER, help="Args forwarded to claude")

    smart_parser = sub.add_parser("smart", help="Try real Anthropic first, handoff on limit")
    smart_parser.add_argument("claude_args", nargs=argparse.REMAINDER, help="Args forwarded to claude")

    continue_parser = sub.add_parser("continue", help="Resume last Claude Code session on free backends")
    continue_parser.add_argument("--session-id", help="Claude Code session UUID")

    prevhandoff_parser = sub.add_parser(
        "prevhandoff",
        help="Export session, archive it, start fresh on free backends",
    )
    prevhandoff_parser.add_argument("--session-id", help="Claude Code session UUID")

    sub.add_parser("setup", help="Interactive setup for keys and routing")
    sub.add_parser("init", help="Create config/localbot.yaml from example (dev)")
    sub.add_parser("doctor", help="Validate config, env vars, and tools")
    sub.add_parser("serve", help="Start the proxy in foreground")

    claude_parser = sub.add_parser("claude", help="Launch Claude Code via the proxy")
    claude_parser.add_argument("--model", help="Override Claude Code model alias")
    claude_parser.add_argument("claude_args", nargs=argparse.REMAINDER, help="Args forwarded to claude")

    sub.add_parser("usage", help="Show spend and remaining budget")
    sub.add_parser("stop", help="Stop the background proxy")
    sub.add_parser("restart", help="Restart the background proxy")
    sub.add_parser("install", help="Install overdraft command and background proxy")

    open_parser = sub.add_parser("open", help="Open a file in Cursor/VS Code at a line")
    open_parser.add_argument("location", help="Path, or path:line, or path:start-end")

    find_parser = sub.add_parser("find", help="Search the repo with ripgrep")
    find_parser.add_argument("pattern", help="Regex pattern for rg")
    find_parser.add_argument("--glob", help="Glob filter passed to rg")
    find_parser.add_argument("--open", action="store_true", help="Open the first match in the editor")
    find_parser.add_argument("--limit", type=int, default=20, help="Max matches to print")

    return parser


def main() -> None:
    _load_env()
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        args.command = "run"
        args.model = None
        args.quiet = False
        args.claude_args = []

    commands = {
        "run": cmd_run,
        "smart": cmd_smart,
        "continue": cmd_continue,
        "prevhandoff": cmd_prevhandoff,
        "setup": cmd_setup,
        "init": cmd_init,
        "doctor": cmd_doctor,
        "serve": cmd_serve,
        "claude": cmd_claude,
        "usage": cmd_usage,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "install": cmd_install,
        "open": cmd_open,
        "find": cmd_find,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
