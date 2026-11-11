"""@workflow / @task / @tool / @agent — thin OTel decorators (sync + async)."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportAssignmentType=false

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from traceiq import _enforcement
from traceiq._context import (
    get_request_context,
    merged_trace_attrs,
    restore_context,
    set_context,
    snapshot_context,
)
from traceiq._ids import stable_workflow_id
from traceiq._init import get_provider

F = TypeVar("F", bound=Callable[..., Any])

TRACER_NAME = "traceiq"


def _tracer():
    provider = get_provider()
    if provider is not None:
        return provider.get_tracer(TRACER_NAME, "0.1.0")
    return trace.get_tracer(TRACER_NAME, "0.1.0")


def _apply_kind_attrs(span: Any, kind: str, span_name: str, agent_name: str | None) -> None:
    span.set_attribute("traceiq.step_type", kind)
    if kind == "workflow":
        span.set_attribute("traceiq.trace.root", True)
        wf_id = stable_workflow_id(span_name)
        span.set_attribute("traceiq.workflow_id", wf_id)
        set_context(workflow_id=wf_id)
    if kind == "agent":
        label = agent_name or span_name
        span.set_attribute("traceiq.agent_name", label)
        set_context(agent_name=label)


def _stamp_final_context(span: Any) -> None:
    """Stamp current request context onto this span (success or failure)."""
    for key, value in merged_trace_attrs().items():
        span.set_attribute(key, value)


def _guard(kind: str, span_name: str) -> None:
    """Refuse to start a blocked agent's run (see _enforcement)."""
    if kind == "workflow":
        _enforcement.check(stable_workflow_id(span_name))
    elif kind == "agent":
        _enforcement.check(get_request_context().workflow_id or None)


def _decorate(kind: str, name: str | None, agent_name: str | None, fn: F) -> F:
    span_name = name or fn.__name__

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            _guard(kind, span_name)
            snap = snapshot_context()
            try:
                with _tracer().start_as_current_span(span_name) as span:
                    _apply_kind_attrs(span, kind, span_name, agent_name)
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        # Stamp before exit so failed runs keep product/project (R3).
                        _stamp_final_context(span)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        span.record_exception(exc)
                        raise
                    _stamp_final_context(span)
                    span.set_status(Status(StatusCode.OK))
                    return result
            finally:
                restore_context(snap)

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        _guard(kind, span_name)
        snap = snapshot_context()
        try:
            with _tracer().start_as_current_span(span_name) as span:
                _apply_kind_attrs(span, kind, span_name, agent_name)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    _stamp_final_context(span)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    raise
                _stamp_final_context(span)
                span.set_status(Status(StatusCode.OK))
                return result
        finally:
            restore_context(snap)

    return sync_wrapper  # type: ignore[return-value]


def _factory(kind: str, name: str | None = None, agent_name: str | None = None):
    def decorator(fn: F) -> F:
        return _decorate(kind, name, agent_name, fn)

    return decorator


def workflow(name: str | None = None) -> Any:
    if callable(name):
        return _decorate("workflow", name.__name__, None, name)
    return _factory("workflow", name=name)


def task(name: str | None = None) -> Any:
    if callable(name):
        return _decorate("task", name.__name__, None, name)
    return _factory("task", name=name)


def tool(name: str | None = None) -> Any:
    if callable(name):
        return _decorate("tool", name.__name__, None, name)
    return _factory("tool", name=name)


def agent(name: str | None = None) -> Any:
    if callable(name):
        return _decorate("agent", name.__name__, name.__name__, name)
    return _factory("agent", name=name, agent_name=name)
