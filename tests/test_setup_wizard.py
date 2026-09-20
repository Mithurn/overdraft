from localbot.setup_wizard import build_config


def test_build_config_enables_cloudflare_and_groq():
    values = {
        "CLOUDFLARE_ACCOUNT_ID": "acct",
        "CLOUDFLARE_API_TOKEN": "token",
        "GROQ_API_KEY": "gsk_test",
        "LOCALBOT_PROXY_KEY": "sk-test",
    }
    config = build_config(values)
    assert config["providers"]["cloudflare"]["enabled"] is True
    assert config["providers"]["groq"]["enabled"] is True
    assert config["providers"]["openrouter"]["enabled"] is False
    assert config["routing"]["primary"] == "cloudflare-glm-47-flash"
    assert "groq-gpt-oss-20b" in config["routing"]["fallbacks"]
