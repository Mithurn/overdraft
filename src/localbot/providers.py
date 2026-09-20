from __future__ import annotations

import os
from typing import Any

from localbot.config import LocalbotConfig, ModelSpec, ProviderSpec

OPENAI_COMPAT_PROVIDERS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}


def _provider_token(provider: ProviderSpec) -> str:
    if provider.name == "cloudflare":
        return os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CLOUDFLARE_API_KEY", "")
    if provider.api_key_env:
        return os.environ.get(provider.api_key_env, "")
    return ""


def provider_available(config: LocalbotConfig, model_id: str) -> bool:
    provider = config.provider_for_model(model_id)
    if not provider.enabled:
        return False
    if provider.name == "cloudflare":
        account_id = os.environ.get(provider.account_id_env or "CLOUDFLARE_ACCOUNT_ID")
        return bool(account_id and _provider_token(provider))
    if provider.name == "ollama":
        return bool(os.environ.get(provider.base_url_env or "OLLAMA_BASE_URL"))
    if provider.api_key_env:
        return bool(os.environ.get(provider.api_key_env))
    return bool(_provider_token(provider))


def build_backend(config: LocalbotConfig, model: ModelSpec) -> dict[str, Any]:
    provider = config.provider_for_model(model.id)
    backend: dict[str, Any] = {
        "provider": provider.name,
        "model_id": model.id,
        "model": model.litellm_model.split("/", 1)[-1],
        "extra_body": model.extra_body,
        "input_cost_per_m": model.input_cost_per_m or 0,
        "output_cost_per_m": model.output_cost_per_m or 0,
        "token": _provider_token(provider),
    }

    if provider.name == "cloudflare":
        account_id = os.environ[provider.account_id_env or "CLOUDFLARE_ACCOUNT_ID"]
        backend["url"] = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
            "/ai/v1/chat/completions"
        )
        return backend

    if provider.name == "ollama":
        base = os.environ.get(provider.base_url_env or "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        backend["url"] = f"{base.rstrip('/')}/v1/chat/completions"
        backend["token"] = "ollama"
        return backend

    if provider.name in OPENAI_COMPAT_PROVIDERS:
        base = provider.base_url or OPENAI_COMPAT_PROVIDERS[provider.name]
        backend["url"] = base if base.endswith("/chat/completions") else f"{base.rstrip('/')}/chat/completions"
        return backend

    if provider.base_url:
        base = provider.base_url.rstrip("/")
        backend["url"] = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        return backend

    raise ValueError(f"Bridge does not support provider: {provider.name}")


def upstream_headers(backend: dict[str, Any], session_affinity: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {backend['token']}",
        "Content-Type": "application/json",
    }
    if backend["provider"] == "cloudflare" and session_affinity:
        headers["x-session-affinity"] = session_affinity
    if backend["provider"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/Mithurn/localbot"
        headers["X-Title"] = "overdraft"
    return headers
