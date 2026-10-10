"""Right column: the record, the reflection log, and earlier runs."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from extraction_engine.engine import ExtractionResult, dumps_payload
from extraction_engine.present import (
    InvoiceView,
    ResumeView,
    digest_events,
    format_trace,
    invoice_view,
    resume_view,
)
from extraction_engine.schemas.registry import SchemaSpec
from extraction_engine.tracing import TraceEvent

_CODE_KINDS = {"validation_error", "retry_feedback", "response", "failure"}
_OPEN_KINDS = {"validation_error", "retry_feedback", "failure"}
_ICONS = {
    "start": ":material/flag:",
    "request": ":material/send:",
    "response": ":material/reply:",
    "validation_error": ":material/error:",
    "retry_feedback": ":material/replay:",
    "success": ":material/check_circle:",
    "failure": ":material/cancel:",
    "info": ":material/info:",
}


def render_results(spec: SchemaSpec) -> None:
    st.subheader("Results", icon=":material/fact_check:", anchor=False)
    result = st.session_state.get("result")
    if not isinstance(result, ExtractionResult):
        if str(st.session_state.get("raw_text", "")).strip():
            message = (
                "Extract when the source looks right. "
                "The log will list each attempt, the ValidationError, and the correction sent back."
            )
        else:
            message = (
                "Load a sample or paste source text, then extract. "
                "The log lists each attempt, the ValidationError, and the correction sent back to the model."
            )
        st.info(message, icon=":material/play_arrow:")
        return

    if result.schema_key != spec.key:
        st.warning(
            f"Showing the last {result.schema_label} run. The selected agent is now {spec.label}.",
            icon=":material/history:",
        )

    _metrics(result)
    if result.ok:
        st.success(f"{result.schema_label} accepted by {result.provider_label}.")
    else:
        st.error(result.error_message or "Extraction failed.")
    _badges(result)

    if result.checks:
        st.markdown("**Rules that passed**")
        for check in result.checks:
            st.markdown(f"- {check}")

    if result.ok and isinstance(result.data, dict):
        _record(result.schema_key, result.data)

    st.subheader("Execution and reflection log", icon=":material/account_tree:", anchor=False)
    if not result.events:
        st.caption("No events were recorded.")
    else:
        for index, event in enumerate(result.events, start=1):
            _step(index, event)

    st.subheader("Validated JSON", icon=":material/data_object:", anchor=False)
    if result.ok and result.data is not None:
        st.json(result.data, expanded=True)
    else:
        st.caption("A JSON document appears here when the schema accepts the extraction.")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with st.container(horizontal=True):
        if result.ok and result.data is not None:
            st.download_button(
                "Download JSON",
                data=dumps_payload(result.data),
                file_name=f"{result.schema_key}-{stamp}.json",
                mime="application/json",
                key="download-json",
                icon=":material/download:",
                width="stretch",
            )
        st.download_button(
            "Download trace",
            data=format_trace(
                schema_label=result.schema_label,
                provider_label=result.provider_label,
                model_name=result.model_name,
                ok=result.ok,
                attempts=result.attempts,
                error_message=result.error_message,
                events=result.events,
            ),
            file_name=f"{result.schema_key}-trace-{stamp}.txt",
            mime="text/plain",
            key="download-trace",
            icon=":material/description:",
            width="stretch",
        )

    _history(result)


def _metrics(result: ExtractionResult) -> None:
    status, attempts, latency, model = st.columns(4)
    status.metric(
        "Status",
        "Valid" if result.ok else "Rejected",
        border=True,
        icon=":material/check_circle:" if result.ok else ":material/error:",
    )
    attempts.metric("Attempts", result.attempts, border=True, icon=":material/replay:")
    latency.metric("Latency", f"{result.latency_ms / 1000:.1f}s", border=True, icon=":material/timer:")
    model.metric("Model", result.model_name, border=True, icon=":material/smart_toy:")


def _badges(result: ExtractionResult) -> None:
    digest = digest_events(result.events)
    with st.container(horizontal=True, gap="small"):
        st.badge(f"{result.attempts} attempts", color="gray", icon=":material/replay:")
        if digest.validation_errors:
            label = "validation error" if digest.validation_errors == 1 else "validation errors"
            st.badge(f"{digest.validation_errors} {label}", color="orange", icon=":material/error:")
        if digest.corrections:
            label = "correction" if digest.corrections == 1 else "corrections"
            st.badge(f"{digest.corrections} {label}", color="blue", icon=":material/replay:")
        if digest.rejected_fields:
            st.badge(
                "Rejected " + ", ".join(digest.rejected_fields),
                color="red",
                icon=":material/rule:",
            )


def _record(schema_key: str, data: dict[str, object]) -> None:
    if schema_key == "invoice":
        _invoice(invoice_view(data))
    elif schema_key == "resume":
        _resume(resume_view(data))


def _invoice(view: InvoiceView) -> None:
    with st.container(border=True):
        st.markdown("**Invoice**")
        if view.facts:
            st.table(view.facts, border="horizontal")
        if view.lines:
            st.dataframe(
                view.lines,
                hide_index=True,
                column_config={
                    "Description": st.column_config.TextColumn("Description"),
                    "Quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                    "Unit price": st.column_config.NumberColumn(f"Unit price ({view.currency})", format="%.2f"),
                    "Amount": st.column_config.NumberColumn(f"Amount ({view.currency})", format="%.2f"),
                },
                alt="Invoice lines with quantity, unit price, and line amount",
            )
        else:
            st.caption("No line items in this record.")
        if view.notes:
            st.caption(view.notes)


def _resume(view: ResumeView) -> None:
    with st.container(border=True):
        st.markdown("**Resume**")
        if view.facts:
            st.table(view.facts, border="horizontal")
        if view.summary:
            st.caption(view.summary)
        if view.skills:
            st.markdown("**Skills**")
            with st.container(horizontal=True, gap="small"):
                for skill in view.skills[:24]:
                    st.badge(skill, color="gray")
            if len(view.skills) > 24:
                st.caption(f"{len(view.skills) - 24} more skills are in the JSON.")
        for role in view.roles:
            with st.container(border=True):
                st.markdown(f"**{role.title}**")
                st.caption(f"{role.employer} · {role.dates}")
                for line in role.highlights:
                    st.markdown(f"- {line}")


def _step(index: int, event: TraceEvent) -> None:
    label = f"{index}. {event.title}"
    if event.attempt is not None:
        label = f"{label} · attempt {event.attempt}"
    with st.expander(label, expanded=event.kind in _OPEN_KINDS, type="step", icon=_ICONS.get(event.kind)):
        st.caption(event.timestamp)
        if event.fields:
            st.caption("Fields: " + ", ".join(event.fields))
        if not event.detail:
            return
        if event.kind in _CODE_KINDS:
            st.code(event.detail, language="text")
        else:
            st.text(event.detail)


def _history(current: ExtractionResult) -> None:
    history = st.session_state.get("history")
    if not isinstance(history, list):
        return
    earlier = [item for item in history if isinstance(item, ExtractionResult) and item is not current]
    if not earlier:
        return
    with st.expander("Earlier runs", icon=":material/history:"):
        for index, past in enumerate(earlier, start=1):
            state = "Valid" if past.ok else "Rejected"
            label = f"{past.schema_label} · {state} · {past.attempts} attempts · {past.latency_ms} ms"
            if st.button(label, key=f"restore-{index}", icon=":material/history:"):
                st.session_state["result"] = past
                st.rerun()
