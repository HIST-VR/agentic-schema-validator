"""Failures the UI can show without a stack trace."""

from __future__ import annotations


class ExtractionError(Exception):
    """A predictable problem: empty input, unknown schema, missing key."""


class MissingApiKeyError(ExtractionError):
    """The selected provider has no key in the form or the environment."""

    def __init__(self, label: str, env_vars: tuple[str, ...], key_url: str) -> None:
        joined = " or ".join(env_vars)
        super().__init__(
            f"No API key for {label}. Enter one in the form, or set {joined}. Keys: {key_url}"
        )
