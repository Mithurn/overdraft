from localbot.config import HandoffSpec, LocalbotConfig, RoutingSpec, ProxySpec, BudgetSpec, ClaudeCodeSpec
from localbot.handoff import looks_like_limit_error


def _config() -> LocalbotConfig:
    return LocalbotConfig(
        path=__file__,
        proxy=ProxySpec(host="127.0.0.1", port=4000, master_key_env="LOCALBOT_PROXY_KEY"),
        budgets=BudgetSpec(monthly_usd=0),
        providers={},
        routing=RoutingSpec(primary="x", fallbacks=[], claude_aliases=[]),
        claude_code=ClaudeCodeSpec(
            default_model="claude-sonnet-4-20250514",
            subagent_model="claude-haiku-4-20250514",
            effort_level="low",
        ),
        handoff=HandoffSpec(),
    )


def test_limit_detection():
    config = _config()
    assert looks_like_limit_error("You've hit your usage limit", config)
    assert looks_like_limit_error("HTTP 429 too many requests", config)
    assert not looks_like_limit_error("all good", config)
