"""OTLP/HTTP JSON exporter (gzip + bounded retries) + file debug sink."""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from traceiq._enrich import enrich_attributes, filter_for_export

logger = logging.getLogger("traceiq")

OTLP_TRACES_SUFFIX = "/v1/otlp/v1/traces"

# Export runs on the BatchSpanProcessor thread — never the agent's hot path —
# but keep the worst case bounded: 3 attempts, ~10s timeout, short backoff.
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_S = 10
BACKOFF_BASE_S = 0.5
# Server said "try later" or had a transient failure → retry; 4xx otherwise → drop.
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def normalize_otlp_endpoint(endpoint: str) -> str:
    """Accept origin or full traces URL."""
    ep = endpoint.rstrip("/")
    if ep.endswith("/v1/otlp/v1/traces"):
        return ep
    if ep.endswith("/v1/otlp"):
        return f"{ep}/v1/traces"
    return f"{ep}{OTLP_TRACES_SUFFIX}"


def _otlp_any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, bytes):
        return {"bytesValue": value.hex()}
    return {"stringValue": str(value)}


def _otlp_attributes(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _otlp_any_value(v)} for k, v in attrs.items()]


def readable_span_to_otlp(span: ReadableSpan) -> dict[str, Any]:
    ctx = span.get_span_context()
    parent = span.parent
    parent_id = format(parent.span_id, "016x") if parent and parent.is_valid else ""
    # Never re-merge ContextVar here — batch/export threads must not steal
    # another request's product/agent (Claude review R3).
    attrs = enrich_attributes(
        dict(span.attributes or {}), merge_request_context=False
    )
    attrs = filter_for_export(attrs)
    status = span.status
    # OTLP: 0=UNSET, 1=OK, 2=ERROR. Do not map UNSET → OK (R7).
    status_code = 0
    if status is not None:
        from opentelemetry.trace import StatusCode

        if status.status_code == StatusCode.OK:
            status_code = 1
        elif status.status_code == StatusCode.ERROR:
            status_code = 2
    body: dict[str, Any] = {
        "traceId": format(ctx.trace_id, "032x"),
        "spanId": format(ctx.span_id, "016x"),
        "name": span.name,
        "kind": int(span.kind.value) if span.kind is not None else 1,
        "startTimeUnixNano": str(span.start_time or 0),
        "endTimeUnixNano": str(span.end_time or 0),
        "attributes": _otlp_attributes(attrs),
        "status": {"code": status_code},
    }
    if parent_id:
        body["parentSpanId"] = parent_id
    return body


def _post_json(url: str, api_key: str, body: dict[str, Any]) -> None:
    """
    POST gzip'd JSON with bounded retries. Raises the last error on failure.

    Retries network errors and 408/429/5xx (honouring Retry-After up to 5s);
    other 4xx (bad key, bad payload, quota) are not retried.
    """
    data = gzip.compress(json.dumps(body).encode("utf-8"))
    headers = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "Authorization": f"Bearer {api_key}",
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                resp.read()
            return
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                raise
            delay = _retry_after(exc) or _backoff(attempt)
        except (URLError, OSError, TimeoutError):
            if attempt == MAX_ATTEMPTS:
                raise
            delay = _backoff(attempt)
        time.sleep(delay)


def _backoff(attempt: int) -> float:
    return BACKOFF_BASE_S * (2 ** (attempt - 1)) * (0.5 + random.random())


def _retry_after(exc: HTTPError) -> float | None:
    try:
        value = float(exc.headers.get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        return None
    return min(max(value, 0.0), 5.0)


class OTLPJsonSpanExporter(SpanExporter):
    """POST ExportTraceServiceRequest-shaped JSON to TraceIQ OTLP endpoint."""

    def __init__(
        self, endpoint: str, api_key: str, *, service_name: str | None = None
    ) -> None:
        self._url = normalize_otlp_endpoint(endpoint)
        self._api_key = api_key
        self._service_name = service_name or "traceiq-app"

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans:
            return SpanExportResult.SUCCESS
        # Prefer app_name stamped on spans; fall back to init-time service name.
        service_name = self._service_name
        for s in spans:
            attrs = dict(s.attributes or {})
            if attrs.get("traceiq.app_name"):
                service_name = str(attrs["traceiq.app_name"])
                break
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": _otlp_attributes(
                            {"service.name": service_name}
                        )
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "traceiq", "version": "0.1.0"},
                            "spans": [readable_span_to_otlp(s) for s in spans],
                        }
                    ],
                }
            ]
        }
        try:
            _post_json(self._url, self._api_key, payload)
            return SpanExportResult.SUCCESS
        except (URLError, OSError, TimeoutError) as exc:
            logger.warning("OTLP export failed: %s", exc)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class FileSpanExporter(SpanExporter):
    """Local debug: write enriched OTLP-ish JSON files under ./traces/."""

    def __init__(self, directory: str = "./traces") -> None:
        self._dir = directory
        os.makedirs(self._dir, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            doc = readable_span_to_otlp(span)
            path = os.path.join(
                self._dir,
                f"{doc['traceId']}_{doc['spanId']}.json",
            )
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2)
            except OSError as exc:
                logger.warning("file export failed: %s", exc)
                return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
