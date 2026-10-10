"""Left column: provider, agent, source text."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from extraction_engine.engine import MAX_SOURCE_CHARS
from extraction_engine.providers import PROVIDER_LIST, Provider
from extraction_engine.schemas.registry import SchemaSpec, schema_from_label, schema_options
from ui.session import environment_key_name, materialize_key


@dataclass(frozen=True)
class RunRequest:
    provider_key: str
    provider_label: str
    model_name: str
    spec: SchemaSpec
    api_key: str
    max_retries: int


def render_controls() -> RunRequest:
    st.subheader("Inputs", icon=":material/edit_note:", anchor=False)
    with st.container(border=True):
        provider = _provider_picker()
        picked = st.selectbox(
            "Model",
            provider.models,
            index=list(provider.models).index(provider.default_model),
            key=f"model-{provider.key}",
        )
        override = st.text_input(
            "Model override",
            key=f"model-override-{provider.key}",
            placeholder="Leave blank to use the model above",
            help="A model id this provider accepts. The list above is the default set.",
        ).strip()
        model_name = override or str(picked)
        if override:
            st.caption(f"This run uses {model_name}.")

        typed_key = st.text_input(
            "API key",
            type="password",
            placeholder=provider.env_vars[0],
            help="Used for this run only. A saved environment variable or Streamlit secret is used when this is blank.",
        )
        _key_caption(provider, typed_key)
        max_retries = int(
            st.number_input(
                "Max retries",
                min_value=0,
                max_value=8,
                value=3,
                step=1,
                key="retries",
                help="Passed to Instructor. After the first attempt, this is how many corrections can be sent.",
            )
        )

    spec = schema_from_label(
        st.selectbox(
            "Extraction agent",
            [item.label for item in schema_options()],
            index=0,
            key="agent",
        )
    )
    st.caption(spec.blurb)
    with st.container(border=True):
        st.markdown("**Business rules**")
        for rule in spec.rules:
            st.markdown(f"- {rule}")

    with st.expander("How the retry loop works", icon=":material/account_tree:"):
        st.markdown(
            """
            The first attempt copies figures as they are printed.
            Pydantic then runs the business rules on that object.
            A failed check is the next message the model sees, including the exact ValidationError.
            Instructor stops when the schema accepts the object, or when the retry budget is spent.
            """
        )

    with st.container(border=True):
        with st.container(horizontal=True):
            load = st.button(
                "Load sample",
                key="load_sample",
                icon=":material/dataset:",
                width="stretch",
            )
            clear = st.button(
                "Clear text",
                key="clear_text",
                icon=":material/close:",
                width="stretch",
            )
        if load:
            st.session_state["raw_text"] = spec.sample_text
            st.rerun()
        if clear:
            st.session_state["raw_text"] = ""
            st.rerun()

        _apply_upload()
        if st.session_state.get("raw_text", "") == spec.sample_text:
            st.info(spec.sample_note, icon=":material/bug_report:")

        source = st.text_area(
            "Source text",
            key="raw_text",
            height=360,
            placeholder="Paste an invoice, a resume, or load the sample.",
        )
        length = len(source)
        st.caption(f"{length:,} / {MAX_SOURCE_CHARS:,} characters.")
        if length > MAX_SOURCE_CHARS:
            st.warning(
                f"This text is over the {MAX_SOURCE_CHARS:,} character limit.",
                icon=":material/warning:",
            )
        elif not source.strip():
            st.caption("Paste source text, load the sample, or upload a file to extract.")

        if st.button(
            "Extract data",
            type="primary",
            key="extract",
            width="stretch",
            icon=":material/play_arrow:",
            disabled=not source.strip() or length > MAX_SOURCE_CHARS,
        ):
            st.session_state["_run_requested"] = True

    with st.expander("Schema contract", icon=":material/data_object:"):
        st.json(spec.model.model_json_schema())

    return RunRequest(
        provider_key=provider.key,
        provider_label=provider.label,
        model_name=model_name,
        spec=spec,
        api_key=materialize_key(provider.env_vars, typed_key),
        max_retries=max_retries,
    )


def _apply_upload() -> None:
    uploaded = st.file_uploader(
        "Upload a text file",
        type=["txt", "md"],
        key="source_file",
        help="UTF-8 text. Replaces the source box.",
    )
    if uploaded is None:
        return
    if st.session_state.get("_applied_file") == uploaded.file_id:
        return
    st.session_state["_applied_file"] = uploaded.file_id
    st.session_state["raw_text"] = uploaded.getvalue().decode("utf-8", errors="replace")
    st.rerun()


def _provider_picker() -> Provider:
    labels = [item.label for item in PROVIDER_LIST]
    selected = st.selectbox("Provider", labels, index=0, key="provider")
    for item in PROVIDER_LIST:
        if item.label == selected:
            return item
    return PROVIDER_LIST[0]


def _key_caption(provider: Provider, typed_key: str) -> None:
    found = environment_key_name(provider.env_vars)
    if typed_key.strip():
        st.caption("Using the key typed above.")
    elif found:
        st.caption(f"Using {found} from the environment.")
    else:
        st.caption(f"No key yet. Set {provider.key_hint()}, or paste one above. {provider.key_url}")
