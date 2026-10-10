"""In-memory trace of one extraction, including the text sent back on retry."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from pydantic import ValidationError

MAX_VALIDATION_CHARS = 20_000
MAX_RESPONSE_CHARS = 4_000
MAX_TRACEBACK_CHARS = 6_000

_SECRET_LINE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|x-goog-api-key|bearer)\b\s*[:=]\s*\S+"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… truncated {len(text) - limit} characters"


def scrub(text: str, secret: str | None) -> str:
    if not text:
        return text
    if secret:
        text = text.replace(secret, "***")
    return _SECRET_LINE.sub(r"\1=***", text)


def format_exception(error: BaseException) -> str:
    if isinstance(error, ValidationError):
        return clip(str(error), MAX_VALIDATION_CHARS)
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, ValidationError):
        return clip(str(cause), MAX_VALIDATION_CHARS)
    return clip(f"{type(error).__name__}: {error}", MAX_VALIDATION_CHARS)


def format_message(message: object) -> str:
    if isinstance(message, dict):
        role = str(message.get("role", "message"))
        content = message.get("content", "")
        return f"[{role}]\n{_render_content(content)}"
    role = getattr(message, "role", None)
    content = getattr(message, "content", None)
    if role is not None or content is not None:
        return f"[{role or 'message'}]\n{_render_content(content)}"
    return str(message)


def summarize_response(response: object) -> str:
    if response is None:
        return "(empty response)"
    text = _dig_text(response)
    if text:
        return clip(text, MAX_RESPONSE_CHARS)
    return clip(repr(response), MAX_RESPONSE_CHARS)


@dataclass
class TraceEvent:
    kind: str
    title: str
    detail: str
    attempt: int | None = None
    timestamp: str = field(default_factory=utc_now)
    fields: tuple[str, ...] = ()


class TraceCollector:
    """Hooks registered on one Instructor client for a single create() call."""

    def __init__(self, events: list[TraceEvent]) -> None:
        self.events = events
        self._previous: list[object] | None = None
        self._fallback_attempt = 0
        self._last_attempt = 1

    def add(
        self,
        kind: str,
        title: str,
        detail: str,
        attempt: int | None,
        fields: tuple[str, ...] = (),
    ) -> None:
        if self.events:
            last = self.events[-1]
            if last.kind == kind and last.title == title and last.detail == detail:
                return
        self.events.append(
            TraceEvent(kind=kind, title=title, detail=detail, attempt=attempt, fields=fields)
        )

    def on_kwargs(self, *args: object, **kwargs: object) -> None:
        del args
        attempt = _attempt_number(kwargs)
        if attempt is None:
            self._fallback_attempt += 1
            attempt = self._fallback_attempt
        self._last_attempt = attempt
        messages = _message_list(kwargs)
        if self._previous is not None and len(messages) > len(self._previous):
            fresh = messages[len(self._previous) :]
            rendered = "\n\n".join(format_message(item) for item in fresh)
            self.add(
                "retry_feedback",
                f"Correction fed back before attempt {attempt}",
                clip(rendered, MAX_VALIDATION_CHARS),
                attempt,
            )
        self._previous = list(messages)
        model = kwargs.get("model") or "(provider default)"
        self.add(
            "request",
            f"Attempt {attempt} sent",
            f"model={model}\nmessages={len(messages)}",
            attempt,
        )

    def on_response(self, *args: object, **kwargs: object) -> None:
        response = args[0] if args else kwargs.get("response")
        self.add(
            "response",
            f"Attempt {self._last_attempt} response",
            summarize_response(response),
            self._last_attempt,
        )

    def on_parse_error(self, *args: object, **kwargs: object) -> None:
        error = _as_exception(args[0] if args else kwargs.get("error"))
        attempt = _attempt_number(kwargs) or self._last_attempt
        title = "ValidationError" if _is_validation(error) else "Parse error"
        self.add(
            "validation_error",
            title,
            format_exception(error),
            attempt,
            fields=field_paths(error),
        )

    def on_completion_error(self, *args: object, **kwargs: object) -> None:
        error = _as_exception(args[0] if args else kwargs.get("error"))
        attempt = kwargs.get("attempt_number")
        if not isinstance(attempt, int):
            attempt = self._last_attempt
        is_last = bool(kwargs.get("is_last_attempt"))
        if _is_validation(error) and not is_last:
            self.add(
                "info",
                f"Attempt {attempt} failed validation",
                "Instructor sends the ValidationError above to the model on the next attempt.",
                attempt,
            )
            return
        kind = "failure" if is_last else "info"
        title = "Retries exhausted" if is_last else f"Attempt {attempt} failed"
        paths = field_paths(error) if _is_validation(error) else ()
        self.add(kind, title, format_exception(error), attempt, fields=paths)


def attach_hooks(client: Any, collector: TraceCollector) -> None:
    if not hasattr(client, "on"):
        raise TypeError("This client does not expose Instructor hooks.")

    def guard(method: Any) -> Any:
        def wrapper(*args: object, **kwargs: object) -> None:
            try:
                method(*args, **kwargs)
            except Exception as exc:
                collector.add("info", "Trace hook failed", f"{type(exc).__name__}: {exc}", None)

        return wrapper

    client.on("completion:kwargs", guard(collector.on_kwargs))
    client.on("completion:response", guard(collector.on_response))
    client.on("parse:error", guard(collector.on_parse_error))
    client.on("completion:error", guard(collector.on_completion_error))


def record_failed_attempts(events: list[TraceEvent], error: BaseException) -> None:
    """Fallback when hooks did not fire and the exception still carries attempts."""
    if any(event.kind == "validation_error" for event in events):
        return
    attempts = getattr(error, "failed_attempts", None)
    if not isinstance(attempts, Sequence) or isinstance(attempts, (str, bytes)):
        return
    for item in attempts:
        attempt_error = getattr(item, "exception", item)
        number = getattr(item, "attempt_number", None)
        if not isinstance(attempt_error, BaseException):
            attempt_error = RuntimeError(str(attempt_error))
        events.append(
            TraceEvent(
                kind="validation_error",
                title="ValidationError",
                detail=format_exception(attempt_error),
                attempt=number if isinstance(number, int) else None,
                fields=field_paths(attempt_error),
            )
        )


def scrub_events(events: list[TraceEvent], secret: str | None) -> None:
    for event in events:
        event.title = scrub(event.title, secret)
        event.detail = scrub(event.detail, secret)


def _message_list(kwargs: dict[str, Any] | Any) -> list[object]:
    if not isinstance(kwargs, dict):
        return []
    for key in ("messages", "contents"):
        value = kwargs.get(key)
        if isinstance(value, list):
            return value
    return []


def _attempt_number(kwargs: dict[str, Any] | Any) -> int | None:
    if not isinstance(kwargs, dict):
        return None
    direct = kwargs.get("attempt_number")
    if isinstance(direct, int):
        return direct
    meta = kwargs.get("_instructor_meta")
    if isinstance(meta, dict) and isinstance(meta.get("attempt_number"), int):
        return meta["attempt_number"]
    return None


def _as_exception(value: object) -> BaseException:
    if isinstance(value, BaseException):
        return value
    return RuntimeError(repr(value))


def field_paths(error: BaseException) -> tuple[str, ...]:
    """Dot-paths of fields a ValidationError rejected, in first-seen order."""
    target: BaseException | None = error if isinstance(error, ValidationError) else None
    if target is None:
        cause = getattr(error, "__cause__", None)
        target = cause if isinstance(cause, ValidationError) else None
    if not isinstance(target, ValidationError):
        return ()
    paths: list[str] = []
    for item in target.errors():
        loc = item.get("loc") or ()
        text = ".".join(str(part) for part in loc) or "(model)"
        if text not in paths:
            paths.append(text)
    return tuple(paths)


def _is_validation(error: BaseException) -> bool:
    if isinstance(error, ValidationError):
        return True
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, ValidationError):
        return True
    return "validation error" in str(error).lower()


def _render_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text", item.get("content", item))
                parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _dig_text(response: object) -> str | None:
    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        message = getattr(choices[0], "message", None)
        if message is not None:
            parts: list[str] = []
            content = getattr(message, "content", None)
            tool_calls = getattr(message, "tool_calls", None)
            if content:
                parts.append(str(content))
            if tool_calls:
                parts.append(str(tool_calls))
            if parts:
                return "\n".join(parts)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    if isinstance(response, dict):
        for key in ("text", "content", "message"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None
