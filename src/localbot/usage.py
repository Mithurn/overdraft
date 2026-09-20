from __future__ import annotations

from dataclasses import dataclass

from localbot.config import LocalbotConfig
from localbot.tracker import spend_summary


@dataclass
class UsageSnapshot:
    spend_usd: float
    max_budget_usd: float | None
    budget_duration: str | None
    budget_remaining_usd: float | None
    requests_today: int | None
    top_models: list[tuple[str, float]]
    spend_today_usd: float = 0.0


def fetch_usage(config: LocalbotConfig, master_key: str) -> UsageSnapshot:
    _ = master_key
    summary = spend_summary()
    spend_usd = float(summary["spend_usd"])
    max_budget = config.budgets.monthly_usd or None
    remaining = max_budget - spend_usd if max_budget is not None else None

    return UsageSnapshot(
        spend_usd=spend_usd,
        max_budget_usd=max_budget,
        budget_duration="30d" if max_budget else None,
        budget_remaining_usd=remaining,
        requests_today=int(summary["requests"]),
        top_models=list(summary["top_models"]),
        spend_today_usd=float(summary["spend_today_usd"]),
    )


def format_usage(snapshot: UsageSnapshot, config: LocalbotConfig) -> str:
    lines = [
        "LocalBot usage",
        f"  spend: ${snapshot.spend_usd:.6f}",
    ]

    if snapshot.max_budget_usd is not None:
        lines.append(f"  monthly budget: ${snapshot.max_budget_usd:.2f}")
        if snapshot.budget_remaining_usd is not None:
            lines.append(f"  remaining: ${snapshot.budget_remaining_usd:.6f}")

    if config.budgets.daily_usd is not None:
        lines.append(f"  daily budget: ${config.budgets.daily_usd:.2f}")
        lines.append(f"  spent today: ${snapshot.spend_today_usd:.6f}")

    if snapshot.requests_today is not None:
        lines.append(f"  requests: {snapshot.requests_today}")

    if snapshot.top_models:
        lines.append("  top models:")
        for name, amount in snapshot.top_models:
            lines.append(f"    {name}: ${amount:.4f}")

    return "\n".join(lines)
