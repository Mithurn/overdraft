from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelSpec:
    id: str
    litellm_model: str
    input_cost_per_m: float | None = None
    output_cost_per_m: float | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSpec:
    name: str
    enabled: bool
    models: list[ModelSpec]
    account_id_env: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None


@dataclass
class BudgetSpec:
    monthly_usd: float
    daily_usd: float | None = None


@dataclass
class ProxySpec:
    host: str
    port: int
    master_key_env: str
    mode: str = "bridge"


@dataclass
class ClaudeCodeSpec:
    default_model: str
    subagent_model: str
    effort_level: str


@dataclass
class HandoffSpec:
    enabled: bool = True
    limit_patterns: list[str] = field(default_factory=list)


@dataclass
class RoutingSpec:
    primary: str
    fallbacks: list[str]
    claude_aliases: list[str]
    mode: str = "free_only"
    by_alias: dict[str, str] = field(default_factory=dict)

    def model_id_for_alias(self, claude_alias: str) -> str:
        if claude_alias in self.by_alias:
            return self.by_alias[claude_alias]
        for pattern, model_id in self.by_alias.items():
            if pattern.endswith("*") and claude_alias.startswith(pattern[:-1]):
                return model_id
        if "haiku" in claude_alias:
            for pattern, model_id in self.by_alias.items():
                if "haiku" in pattern:
                    return model_id
        if "sonnet" in claude_alias or "opus" in claude_alias:
            for pattern, model_id in self.by_alias.items():
                if "sonnet" in pattern or "opus" in pattern:
                    return model_id
        return self.primary


@dataclass
class LocalbotConfig:
    path: Path
    proxy: ProxySpec
    budgets: BudgetSpec
    providers: dict[str, ProviderSpec]
    routing: RoutingSpec
    claude_code: ClaudeCodeSpec
    handoff: HandoffSpec

    def model_by_id(self, model_id: str) -> ModelSpec:
        for provider in self.providers.values():
            for model in provider.models:
                if model.id == model_id:
                    return model
        raise KeyError(f"Unknown model id: {model_id}")

    def provider_for_model(self, model_id: str) -> ProviderSpec:
        for provider in self.providers.values():
            for model in provider.models:
                if model.id == model_id:
                    return provider
        raise KeyError(f"Unknown model id: {model_id}")

    def enabled_models(self) -> dict[str, ModelSpec]:
        models: dict[str, ModelSpec] = {}
        for provider in self.providers.values():
            if not provider.enabled:
                continue
            for model in provider.models:
                models[model.id] = model
        return models


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_config(path: Path) -> LocalbotConfig:
    raw = yaml.safe_load(path.read_text()) or {}

    proxy_raw = _require(raw, "proxy")
    budgets_raw = _require(raw, "budgets")
    providers_raw = _require(raw, "providers")
    routing_raw = _require(raw, "routing")
    claude_raw = _require(raw, "claude_code")
    handoff_raw = raw.get("handoff") or {}

    providers: dict[str, ProviderSpec] = {}
    for name, provider_data in providers_raw.items():
        models = [
            ModelSpec(
                id=_require(model, "id"),
                litellm_model=_require(model, "litellm_model"),
                input_cost_per_m=model.get("input_cost_per_m"),
                output_cost_per_m=model.get("output_cost_per_m"),
                extra_body=model.get("extra_body") or {},
            )
            for model in provider_data.get("models") or []
        ]
        providers[name] = ProviderSpec(
            name=name,
            enabled=bool(provider_data.get("enabled", False)),
            models=models,
            account_id_env=provider_data.get("account_id_env"),
            api_key_env=provider_data.get("api_key_env"),
            base_url=provider_data.get("base_url"),
            base_url_env=provider_data.get("base_url_env"),
        )

    return LocalbotConfig(
        path=path,
        proxy=ProxySpec(
            host=str(proxy_raw.get("host", "127.0.0.1")),
            port=int(proxy_raw.get("port", 4000)),
            master_key_env=str(proxy_raw.get("master_key_env", "LOCALBOT_PROXY_KEY")),
            mode=str(proxy_raw.get("mode", "bridge")),
        ),
        budgets=BudgetSpec(
            monthly_usd=float(budgets_raw.get("monthly_usd", 0)),
            daily_usd=(
                float(budgets_raw["daily_usd"])
                if budgets_raw.get("daily_usd") is not None
                else None
            ),
        ),
        providers=providers,
        routing=RoutingSpec(
            primary=str(_require(routing_raw, "primary")),
            fallbacks=list(routing_raw.get("fallbacks") or []),
            claude_aliases=list(routing_raw.get("claude_aliases") or []),
            mode=str(routing_raw.get("mode", "free_only")),
            by_alias=dict(routing_raw.get("by_alias") or {}),
        ),
        claude_code=ClaudeCodeSpec(
            default_model=str(_require(claude_raw, "default_model")),
            subagent_model=str(_require(claude_raw, "subagent_model")),
            effort_level=str(claude_raw.get("effort_level", "medium")),
        ),
        handoff=HandoffSpec(
            enabled=bool(handoff_raw.get("enabled", True)),
            limit_patterns=list(handoff_raw.get("limit_patterns") or []),
        ),
    )
