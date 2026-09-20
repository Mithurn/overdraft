import os

from localbot.config import ModelSpec, ProviderSpec
from localbot.providers import build_backend


def test_groq_backend():
    os.environ["GROQ_API_KEY"] = "test-key"
    provider = ProviderSpec(
        name="groq",
        enabled=True,
        models=[],
        api_key_env="GROQ_API_KEY",
    )
    model = ModelSpec(id="groq-gpt-oss-20b", litellm_model="groq/openai/gpt-oss-20b")

    class FakeConfig:
        def provider_for_model(self, model_id: str) -> ProviderSpec:
            return provider

    backend = build_backend(FakeConfig(), model)
    assert backend["url"].endswith("/chat/completions")
    assert backend["model"] == "openai/gpt-oss-20b"
