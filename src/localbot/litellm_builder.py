from __future__ import annotations

import os
from typing import Any

import yaml

from localbot.config import LocalbotConfig, ModelSpec, ProviderSpec
from localbot.paths import LITELLM_CONFIG_PATH


def _cost_per_token(per_m: float | None) -> float | None:
    if per_m is None:
        return None
    return per_m / 1_000_000


def _provider_env(provider: ProviderSpec) -> dict[str, str]:
    env: dict[str, str] = {}
    if provider.api_key_env:
        value = os.environ.get(provider.api_key_env)
        if value:
            env[provider.api_key_env] = value
    if provider.account_id_env:
        value = os.environ.get(provider.account_id_env)
        if value:
            env[provider.account_id_env] = value
    if provider.base_url_env:
        value = os.environ.get(provider.base_url_env)
        if value:
            env[provider.base_url_env] = value
    return env


def _litellm_params(
    provider: ProviderSpec,
    model: ModelSpec,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model.litellm_model,
    }

    if provider.api_key_env:
        params["api_key"] = f"os.environ/{provider.api_key_env}"

    if provider.name == "cloudflare" and provider.account_id_env:
        params["api_key"] = f"os.environ/{provider.api_key_env}"

    if provider.base_url:
        params["api_base"] = provider.base_url

    if provider.base_url_env:
        params["api_base"] = f"os.environ/{provider.base_url_env}"

    model_info: dict[str, Any] = {}
    input_cost = _cost_per_token(model.input_cost_per_m)
    output_cost = _cost_per_token(model.output_cost_per_m)
    if input_cost is not None:
        model_info["input_cost_per_token"] = input_cost
    if output_cost is not None:
        model_info["output_cost_per_token"] = output_cost
    if model_info:
        params["model_info"] = model_info

    if model.extra_body:
        params["extra_body"] = model.extra_body

    return params


def build_litellm_config(config: LocalbotConfig, master_key: str) -> dict[str, Any]:
    enabled_models = config.enabled_models()
    primary = config.model_by_id(config.routing.primary)
    primary_provider = _provider_for_model(config, primary.id)

    model_list: list[dict[str, Any]] = []
    aliases = set(config.routing.claude_aliases)
    aliases.add(config.claude_code.default_model)
    aliases.add(config.claude_code.subagent_model)

    primary_params = _litellm_params(primary_provider, primary)

    for alias in sorted(aliases):
        model_list.append(
            {
                "model_name": alias,
                "litellm_params": primary_params,
            }
        )

    for model_id, model in enabled_models.items():
        if model_id == config.routing.primary:
            continue
        provider = _provider_for_model(config, model_id)
        model_list.append(
            {
                "model_name": model_id,
                "litellm_params": _litellm_params(provider, model),
            }
        )

    litellm_settings: dict[str, Any] = {
        "drop_params": True,
        "set_verbose": False,
        "callbacks": ["localbot.tracker.proxy_handler_instance"],
    }

    fallback_targets = [
        model_id
        for model_id in config.routing.fallbacks
        if model_id in enabled_models
    ]
    if fallback_targets:
        litellm_settings["fallbacks"] = [
            {config.claude_code.default_model: fallback_targets}
        ]

    general_settings: dict[str, Any] = {
        "master_key": master_key,
        "store_model_in_db": True,
    }

    if config.budgets.monthly_usd > 0:
        general_settings["max_budget"] = config.budgets.monthly_usd
        general_settings["budget_duration"] = "30d"

    return {
        "model_list": model_list,
        "litellm_settings": litellm_settings,
        "general_settings": general_settings,
    }


def _provider_for_model(config: LocalbotConfig, model_id: str) -> ProviderSpec:
    for provider in config.providers.values():
        if not provider.enabled:
            continue
        for model in provider.models:
            if model.id == model_id:
                return provider
    raise KeyError(f"No enabled provider for model id: {model_id}")


def write_litellm_config(config: LocalbotConfig, master_key: str) -> None:
    LITELLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = build_litellm_config(config, master_key)
    LITELLM_CONFIG_PATH.write_text(yaml.safe_dump(payload, sort_keys=False))


def provider_runtime_env(config: LocalbotConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    for provider in config.providers.values():
        if not provider.enabled:
            continue
        env.update(_provider_env(provider))
        if provider.name == "cloudflare":
            token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get(
                "CLOUDFLARE_API_KEY"
            )
            if token:
                env["CLOUDFLARE_API_TOKEN"] = token
                env["CLOUDFLARE_API_KEY"] = token
    return env
