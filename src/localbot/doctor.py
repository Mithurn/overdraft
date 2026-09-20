from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from localbot.config import LocalbotConfig


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_doctor(config: LocalbotConfig) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(_check_binary("claude", "Claude Code CLI"))
    results.append(_check_binary("python3", "Python"))
    results.append(_check_env(config.proxy.master_key_env, "Proxy master key"))

    for provider in config.providers.values():
        if not provider.enabled:
            continue
        if provider.api_key_env:
            results.append(_check_env(provider.api_key_env, f"{provider.name} API key"))
        if provider.account_id_env:
            results.append(
                _check_env(provider.account_id_env, f"{provider.name} account id")
            )

    primary = config.routing.primary
    try:
        backend = config.model_by_id(primary)
        provider = config.provider_for_model(primary)
        backend_name = backend.litellm_model.split("/", 1)[-1]
        results.append(
            CheckResult(
                "backend model",
                True,
                f"{provider.name}/{backend_name} (alias {config.claude_code.default_model})",
            )
        )
        for model_id in config.routing.fallbacks:
            try:
                fb = config.model_by_id(model_id)
                fb_provider = config.provider_for_model(model_id)
                fb_name = fb.litellm_model.split("/", 1)[-1]
                results.append(
                    CheckResult(
                        "fallback model",
                        True,
                        f"{fb_provider.name}/{fb_name}",
                    )
                )
            except KeyError as exc:
                results.append(CheckResult("fallback model", False, str(exc)))
    except KeyError as exc:
        results.append(CheckResult("backend model", False, str(exc)))

    if config.providers.get("ollama", None) and config.providers["ollama"].enabled:
        results.append(_check_binary("ollama", "Ollama"))

    return results


def _check_binary(name: str, label: str) -> CheckResult:
    path = shutil.which(name)
    if not path:
        return CheckResult(label, False, f"{name} not found in PATH")
    return CheckResult(label, True, path)


def _check_env(name: str, label: str) -> CheckResult:
    value = os.environ.get(name)
    if not value:
        return CheckResult(label, False, f"Missing env var {name}")
    return CheckResult(label, True, f"{name} is set")


def format_doctor(results: list[CheckResult]) -> str:
    lines = ["LocalBot doctor"]
    failed = 0
    for result in results:
        status = "ok" if result.ok else "FAIL"
        lines.append(f"  [{status}] {result.name}: {result.detail}")
        if not result.ok:
            failed += 1
    lines.append(f"{len(results) - failed}/{len(results)} checks passed")
    return "\n".join(lines)


def claude_version() -> str | None:
    if not shutil.which("claude"):
        return None
    try:
        completed = subprocess.run(
            ["claude", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output or None
