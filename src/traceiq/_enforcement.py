"""
Budget enforcement — stop a run *before* it spends, when an admin has set an
enforce budget on this agent and it is used up.

TraceIQ keeps recording every trace (data is never dropped); this module asks
GET {endpoint}/v1/guardrails/enforcement which agents are blocked, caches the
answer for the server's ttl_seconds, and @workflow / @agent raise
BudgetExceededError instead of running a blocked agent.

Fail-open: if TraceIQ can't be reached, runs are allowed (the last known list
is kept). The first check fetches synchronously (≤ 2s); later refreshes happen
in a background thread so the agent's call path never waits on TraceIQ.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from traceiq._context import get_globals

logger = logging.getLogger("traceiq")

FETCH_TIMEOUT_S = 2
DEFAULT_TTL_S = 60


class BudgetExceededError(RuntimeError):
    """Raised when this agent's TraceIQ enforce budget is used up for the current window."""

    def __init__(self, info: dict[str, Any]):
        self.info = info
        super().__init__(
            f"TraceIQ budget '{info.get('budget')}' is used up "
            f"(${info.get('spent_usd')} of ${info.get('amount_usd')}); "
            f"runs are blocked until {info.get('resets_at')}."
        )


_state: dict[str, Any] = {"enabled": True, "blocked": {}, "fetched_at": None, "ttl": DEFAULT_TTL_S}
_lock = threading.Lock()
_refreshing = threading.Event()


def configure(enabled: bool) -> None:
    with _lock:
        _state.update(enabled=bool(enabled), blocked={}, fetched_at=None, ttl=DEFAULT_TTL_S)


def _origin(endpoint: str) -> str:
    ep = endpoint.rstrip("/")
    for suffix in ("/v1/otlp/v1/traces", "/v1/otlp"):
        if ep.endswith(suffix):
            return ep[: -len(suffix)]
    return ep


def _fetch() -> None:
    g = get_globals()
    try:
        req = Request(
            f"{_origin(g.endpoint)}/v1/guardrails/enforcement",
            headers={"Authorization": f"Bearer {g.api_key}", "Accept": "application/json"},
        )
        with urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            body = json.loads(resp.read() or b"{}")
        blocked = {
            (b.get("app_name") or "", b.get("workflow_id") or "", b.get("environment") or ""): b
            for b in body.get("blocked_agents") or []
        }
        with _lock:
            _state.update(blocked=blocked, fetched_at=time.monotonic(), ttl=int(body.get("ttl_seconds") or DEFAULT_TTL_S))
    except Exception as exc:  # noqa: BLE001 — fail open, keep the last known list
        logger.debug("budget status check failed: %s", exc)
        with _lock:
            _state["fetched_at"] = time.monotonic()  # back off until the next ttl
    finally:
        _refreshing.clear()


def _ensure_fresh() -> None:
    with _lock:
        fetched_at, ttl = _state["fetched_at"], _state["ttl"]
    if fetched_at is None:
        _fetch()  # first check: synchronous, bounded by FETCH_TIMEOUT_S
    elif time.monotonic() - fetched_at > ttl and not _refreshing.is_set():
        _refreshing.set()
        threading.Thread(target=_fetch, name="traceiq-budget-status", daemon=True).start()


def check(workflow_id: str | None) -> None:
    """Raise BudgetExceededError if the agent identified by workflow_id is blocked."""
    g = get_globals()
    if not _state["enabled"] or not g.initialized or not g.endpoint or not g.api_key:
        return
    _ensure_fresh()
    key = (g.app_name or "", workflow_id or "unknown", g.environment or "default")
    with _lock:
        info = _state["blocked"].get(key)
    if info is not None:
        raise BudgetExceededError(info)
