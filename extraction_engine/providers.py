"""Model providers. Gemini is the default. OpenAI and SpaceXAI share the same loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Any, Literal

from extraction_engine.errors import MissingApiKeyError

ProviderKind = Literal["google", "openai", "openai_compatible"]


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    default_model: str
    models: tuple[str, ...]
    env_vars: tuple[str, ...]
    key_url: str
    kind: ProviderKind
    base_url: str | None = None
    # Gemini thinking models reject an explicit temperature on some API revisions.
    supports_temperature: bool = True

    def key_hint(self) -> str:
        return " or ".join(self.env_vars)


GOOGLE = Provider(
    key="google",
    label="Google Gemini",
    default_model="gemini-3.5-flash",
    models=("gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-pro"),
    env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    key_url="https://aistudio.google.com/apikey",
    kind="google",
    supports_temperature=False,
)

OPENAI = Provider(
    key="openai",
    label="OpenAI",
    default_model="gpt-4.1-mini",
    models=("gpt-4.1-mini", "gpt-4o-mini"),
    env_vars=("OPENAI_API_KEY",),
    key_url="https://platform.openai.com/api-keys",
    kind="openai",
)

# SpaceXAI is served by the xAI API. Instructor talks to it through the
# OpenAI-compatible client documented at https://docs.x.ai.
SPACEXAI = Provider(
    key="xai",
    label="SpaceXAI (xAI)",
    default_model="grok-4.7",
    models=("grok-4.7",),
    env_vars=("XAI_API_KEY",),
    key_url="https://console.x.ai/",
    kind="openai_compatible",
    base_url="https://api.x.ai/v1",
)

PROVIDER_LIST: tuple[Provider, ...] = (GOOGLE, OPENAI, SPACEXAI)
PROVIDERS: dict[str, Provider] = {provider.key: provider for provider in PROVIDER_LIST}


def get_provider(key: str) -> Provider:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        known = ", ".join(PROVIDERS)
        raise KeyError(f"Unknown provider {key!r}. Choose one of: {known}.") from exc


def resolve_api_key(
    provider: Provider,
    explicit: str = "",
    environ: Mapping[str, str] | None = None,
) -> str:
    """Prefer a key typed into the form. Otherwise read the provider's env vars."""
    if explicit.strip():
        return explicit.strip()
    env = os.environ if environ is None else environ
    for name in provider.env_vars:
        value = env.get(name, "").strip()
        if value:
            return value
    raise MissingApiKeyError(provider.label, provider.env_vars, provider.key_url)


def build_client(provider: Provider, model: str, api_key: str) -> Any:
    """Return an Instructor client bound to one provider and model."""
    import instructor

    mode = instructor.Mode.TOOLS
    if provider.kind == "google":
        return instructor.from_provider(
            f"google/{model}",
            api_key=api_key,
            mode=mode,
        )
    if provider.kind == "openai":
        return instructor.from_provider(
            f"openai/{model}",
            api_key=api_key,
            mode=mode,
        )
    if provider.kind == "openai_compatible":
        from openai import OpenAI

        raw = OpenAI(api_key=api_key, base_url=provider.base_url)
        return instructor.from_openai(raw, mode=mode)
    raise KeyError(f"Unsupported provider kind {provider.kind!r}.")
