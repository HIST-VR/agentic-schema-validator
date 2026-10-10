"""Streamlit entry point for the agentic schema validator."""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from extraction_engine.engine import extract, requires_provider_call
from ui.controls import render_controls
from ui.results import render_results
from ui.session import init_state, remember

load_dotenv()

st.set_page_config(
    page_title="Schema validator",
    page_icon=":material/rule:",
    layout="wide",
    initial_sidebar_state="collapsed",
)
init_state()

st.badge("Agentic extraction", color="primary", icon=":material/account_tree:")
st.title("Schema validator", anchor=False)
st.markdown(
    "Messy text goes in. A Pydantic schema checks the business rules, and "
    "Instructor sends each ValidationError back to the model until the record "
    "is accepted or the retry budget runs out."
)

controls, results = st.columns([1, 1.12], gap="large")
with results:
    output = st.container()
with controls:
    request = render_controls()

run = st.session_state.pop("_run_requested", False)
with output:
    if run:
        source = st.session_state.get("raw_text", "")
        kwargs = {
            "source_text": source,
            "schema_key": request.spec.key,
            "provider_key": request.provider_key,
            "model_name": request.model_name,
            "api_key": request.api_key,
            "max_retries": request.max_retries,
        }
        if requires_provider_call(
            source_text=source,
            model_name=request.model_name,
            max_retries=request.max_retries,
            api_key=request.api_key,
        ):
            with st.spinner("Calling the model and checking the schema."):
                result = extract(**kwargs)
        else:
            result = extract(**kwargs)
        st.session_state["result"] = result
        remember(result)
    render_results(request.spec)
