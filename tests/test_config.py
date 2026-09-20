from pathlib import Path

from localbot.config import load_config
from localbot.litellm_builder import build_litellm_config


def test_example_config_loads():
    path = Path(__file__).resolve().parents[1] / "config" / "localbot.example.yaml"
    config = load_config(path)
    assert config.routing.primary == "cloudflare-glm-47-flash"
    assert config.routing.mode == "free_only"
    assert config.handoff.enabled is True
    assert config.routing.model_id_for_alias("claude-haiku-4-20250514") == (
        "cloudflare-glm-47-flash"
    )
    assert config.routing.fallbacks == [
        "cloudflare-gpt-oss-20b",
        "groq-gpt-oss-20b",
    ]


def test_litellm_config_has_claude_aliases():
    path = Path(__file__).resolve().parents[1] / "config" / "localbot.example.yaml"
    config = load_config(path)
    litellm_config = build_litellm_config(config, "sk-test")
    names = {entry["model_name"] for entry in litellm_config["model_list"]}
    assert "claude-sonnet-4-20250514" in names
    assert litellm_config["general_settings"]["max_budget"] == 20.0
