"""Process globals + per-request ContextVar (locked §3.1 fields only)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from typing import Any, Iterator

INGEST_SOURCE = "sdk"

# Allowlisted ContextVar keys (set_context)
_CONTEXT_KEYS = frozenset(
    {
        "workflow_id",
        "agent_name",
        "product_id",
        "product_name",
        "project_id",
        "project_name",
        "customer_id",
        "customer_name",
        "user_email",
    }
)


@dataclass
class _Globals:
    app_name: str = ""
    environment: str = ""
    ingest_source: str = INGEST_SOURCE
    api_key: str = ""
    endpoint: str = ""
    export_mode: str = "otlp"
    disable_batch: bool = False
    initialized: bool = False


@dataclass
class _RequestContext:
    workflow_id: str = ""
    agent_name: str = ""
    product_id: str = ""
    product_name: str = ""
    project_id: str = ""
    project_name: str = ""
    # End customer (B2B tenant) this request is for — cost vs revenue per customer
    customer_id: str = ""
    customer_name: str = ""
    # Employee running an internal agent — matched to TraceIQ People by email
    user_email: str = ""


_globals = _Globals()
_request_ctx: ContextVar[_RequestContext] = ContextVar(
    "traceiq_request_ctx", default=_RequestContext()
)


def configure_globals(
    *,
    app_name: str = "",
    environment: str = "",
    api_key: str = "",
    endpoint: str = "",
    export_mode: str = "otlp",
    disable_batch: bool = False,
) -> None:
    _globals.app_name = app_name or ""
    _globals.environment = environment or ""
    _globals.ingest_source = INGEST_SOURCE
    _globals.api_key = api_key or ""
    _globals.endpoint = (endpoint or "").rstrip("/")
    _globals.export_mode = export_mode or "otlp"
    _globals.disable_batch = bool(disable_batch)
    _globals.initialized = True


def get_globals() -> _Globals:
    return _globals


def set_context(**kwargs: Any) -> None:
    """Per-request dims. Allowed: workflow_id, agent_name, product_*, project_*, customer_*, user_email."""
    unknown = set(kwargs) - _CONTEXT_KEYS
    if unknown:
        raise TypeError(f"Unknown set_context fields: {sorted(unknown)}")
    current = _request_ctx.get()
    data = {f.name: getattr(current, f.name) for f in fields(current)}
    for key, value in kwargs.items():
        if value is None:
            continue
        data[key] = str(value)
    _request_ctx.set(_RequestContext(**data))


def clear_context() -> None:
    _request_ctx.set(_RequestContext())


def snapshot_context() -> _RequestContext:
    """Copy of current request context (for decorator enter/exit restore)."""
    current = _request_ctx.get()
    return _RequestContext(**{f.name: getattr(current, f.name) for f in fields(current)})


def restore_context(snap: _RequestContext) -> None:
    """Replace request context with a prior snapshot (prevents cross-request leak)."""
    _request_ctx.set(
        _RequestContext(**{f.name: getattr(snap, f.name) for f in fields(snap)})
    )


@contextmanager
def scoped_context(**kwargs: Any) -> Iterator[None]:
    """
    Apply set_context for a block, then restore the previous snapshot.

    Decorators use this so @agent / @workflow cannot leak into the next request.
    """
    snap = snapshot_context()
    try:
        if kwargs:
            set_context(**kwargs)
        yield
    finally:
        restore_context(snap)


def get_request_context() -> _RequestContext:
    return _request_ctx.get()


def merged_trace_attrs() -> dict[str, str]:
    """Globals + request context for stamping on every span (§3.1)."""
    g = _globals
    r = _request_ctx.get()
    out: dict[str, str] = {
        "traceiq.ingest_source": INGEST_SOURCE,
    }
    if g.app_name:
        out["traceiq.app_name"] = g.app_name
    if g.environment:
        out["traceiq.environment"] = g.environment
    if r.workflow_id:
        out["traceiq.workflow_id"] = r.workflow_id
    if r.agent_name:
        out["traceiq.agent_name"] = r.agent_name
    if r.product_id:
        out["traceiq.product.id"] = r.product_id
    if r.product_name:
        out["traceiq.product.name"] = r.product_name
    if r.project_id:
        out["traceiq.project.id"] = r.project_id
    if r.project_name:
        out["traceiq.project.name"] = r.project_name
    if r.customer_id:
        out["traceiq.customer.id"] = r.customer_id
    if r.customer_name:
        out["traceiq.customer.name"] = r.customer_name
    if r.user_email:
        out["traceiq.user.email"] = r.user_email.strip().lower()
    return out
