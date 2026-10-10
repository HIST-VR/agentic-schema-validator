import pytest

from extraction_engine.errors import MissingApiKeyError
from extraction_engine.providers import GOOGLE, OPENAI, resolve_api_key


def test_explicit_key_wins_over_the_environment() -> None:
    key = resolve_api_key(GOOGLE, " typed-key ", {"GEMINI_API_KEY": "env-key"})
    assert key == "typed-key"


def test_environment_falls_through_provider_variable_names() -> None:
    assert resolve_api_key(GOOGLE, "", {"GOOGLE_API_KEY": "google-env"}) == "google-env"
    assert resolve_api_key(OPENAI, "", {"OPENAI_API_KEY": "sk-openai"}) == "sk-openai"


def test_missing_key_names_the_variables_and_the_key_page() -> None:
    with pytest.raises(MissingApiKeyError, match="GEMINI_API_KEY") as caught:
        resolve_api_key(GOOGLE, "  ", {})
    assert "aistudio.google.com" in str(caught.value)
