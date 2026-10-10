"""Session keys, saved runs, and where the API key comes from."""

from __future__ import annotations

import os

import streamlit as st

from extraction_engine.engine import ExtractionResult

HISTORY_LIMIT = 6


def init_state() -> None:
    st.session_state.setdefault("raw_text", "")
    st.session_state.setdefault("history", [])


def remember(result: ExtractionResult) -> None:
    history = st.session_state.setdefault("history", [])
    history.insert(0, result)
    del history[HISTORY_LIMIT:]


def materialize_key(names: tuple[str, ...], typed: str) -> str:
    if typed.strip():
        return typed.strip()
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return secret(names)


def environment_key_name(names: tuple[str, ...]) -> str | None:
    for name in names:
        if os.getenv(name, "").strip():
            return name
    if secret(names):
        return "a Streamlit secret"
    return None


def secret(names: tuple[str, ...]) -> str:
    """Read a Streamlit secret when one is configured.

    ``load_if_toml_exists`` stays quiet when no secrets file is present, which
    is the normal local case. Community Cloud writes that file before startup,
    and string values are also copied into the process environment.
    """
    try:
        if not st.secrets.load_if_toml_exists():
            return ""
        for name in names:
            if name in st.secrets and str(st.secrets[name]).strip():
                return str(st.secrets[name]).strip()
    except Exception:
        return ""
    return ""
