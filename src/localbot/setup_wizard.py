from __future__ import annotations

import getpass
import os
import secrets
from pathlib import Path
from typing import Any

import yaml

from localbot.commands import ensure_prevhandoff_command
from localbot.config import load_config
from localbot.doctor import format_doctor, run_doctor
from localbot.paths import USER_CONFIG_DIR, USER_CONFIG_PATH, USER_ENV_PATH, example_config_path


PROMPTS: list[tuple[str, str, bool]] = [
    ("CLOUDFLARE_ACCOUNT_ID", "Cloudflare account ID", False),
    ("CLOUDFLARE_API_TOKEN", "Cloudflare API token", True),
    ("GROQ_API_KEY", "Groq API key", True),
    ("OPENROUTER_API_KEY", "OpenRouter API key", True),
    ("DEEPSEEK_API_KEY", "DeepSeek API key", True),
    ("GOOGLE_API_KEY", "Google Gemini API key", True),
    ("OLLAMA_BASE_URL", "Ollama base URL (blank to skip)", False),
]


def _prompt_value(name: str, label: str, secret: bool) -> str:
    existing = os.environ.get(name, "")
    suffix = " [keep existing]" if existing else ""
    if secret:
        value = getpass.getpass(f"{label}{suffix}: ").strip()
    else:
        value = input(f"{label}{suffix}: ").strip()
    return value or existing


def collect_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for name, label, secret in PROMPTS:
        value = _prompt_value(name, label, secret)
        if value:
            values[name] = value
    if "LOCALBOT_PROXY_KEY" not in values:
        values["LOCALBOT_PROXY_KEY"] = secrets.token_urlsafe(24)
    return values


def _provider_enabled(values: dict[str, str], name: str) -> bool:
    if name == "cloudflare":
        return bool(values.get("CLOUDFLARE_ACCOUNT_ID") and values.get("CLOUDFLARE_API_TOKEN"))
    if name == "groq":
        return bool(values.get("GROQ_API_KEY"))
    if name == "openrouter":
        return bool(values.get("OPENROUTER_API_KEY"))
    if name == "deepseek":
        return bool(values.get("DEEPSEEK_API_KEY"))
    if name == "google":
        return bool(values.get("GOOGLE_API_KEY"))
    if name == "ollama":
        return bool(values.get("OLLAMA_BASE_URL"))
    return False


def _fallback_chain(raw: dict[str, Any], values: dict[str, str]) -> tuple[str, list[str]]:
    chain: list[str] = []
    if _provider_enabled(values, "cloudflare"):
        chain.extend(["cloudflare-glm-47-flash", "cloudflare-gpt-oss-20b"])
    if _provider_enabled(values, "groq"):
        chain.append("groq-gpt-oss-20b")
    if _provider_enabled(values, "openrouter"):
        chain.append("openrouter-free")
    if _provider_enabled(values, "deepseek"):
        chain.append("deepseek-chat")
    if _provider_enabled(values, "google"):
        chain.append("google-gemini-flash")
    if _provider_enabled(values, "ollama"):
        chain.append("ollama-qwen-coder")
    if not chain:
        raise SystemExit("No providers configured. Add at least one API key.")
    return chain[0], chain[1:]


def build_config(values: dict[str, str]) -> dict[str, Any]:
    raw = yaml.safe_load(example_config_path().read_text()) or {}
    providers = raw.get("providers") or {}
    for name in list(providers.keys()):
        providers[name]["enabled"] = _provider_enabled(values, name)
    raw["providers"] = providers

    primary, fallbacks = _fallback_chain(raw, values)
    routing = raw.get("routing") or {}
    routing["primary"] = primary
    routing["fallbacks"] = fallbacks
    routing["mode"] = "free_only"
    raw["routing"] = routing
    raw["handoff"] = {"enabled": True, "limit_patterns": []}
    return raw


def write_setup(values: dict[str, str], config: dict[str, Any]) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    env_lines = [f"{key}={value}" for key, value in sorted(values.items())]
    USER_ENV_PATH.write_text("\n".join(env_lines) + "\n")
    os.chmod(USER_ENV_PATH, 0o600)
    USER_CONFIG_PATH.write_text(yaml.safe_dump(config, sort_keys=False))


def run_setup() -> None:
    print("CloudAI setup")
    print("Press Enter to skip optional providers.\n")
    values = collect_env_values()
    config = build_config(values)
    write_setup(values, config)
    for key, value in values.items():
        os.environ[key] = value
    loaded = load_config(USER_CONFIG_PATH)
    ensure_prevhandoff_command()
    print(f"\nWrote {USER_CONFIG_PATH}")
    print(f"Wrote {USER_ENV_PATH}")
    print("Installed /prevhandoff in ~/.claude/commands/")
    print(format_doctor(run_doctor(loaded)))
