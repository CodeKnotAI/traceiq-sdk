"""Lean enrichment — stamp §3 attrs; strip content; allowlist contract."""

from __future__ import annotations

from typing import Any, Sequence

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from traceiq._compat import (
    ensure_model,
    ensure_provider,
    extract_audio_vision_usage,
    extract_cache_usage,
    normalize_tokens,
)
from traceiq._context import merged_trace_attrs
from traceiq._modality import ATTR_MODALITY, infer_modality
from traceiq._step import ATTR_STEP_TYPE, infer_step_type

TRACEIQ_ALLOWLIST = frozenset(
    {
        "traceiq.workflow_id",
        "traceiq.environment",
        "traceiq.app_name",
        "traceiq.agent_name",
        "traceiq.product.id",
        "traceiq.product.name",
        "traceiq.project.id",
        "traceiq.project.name",
        "traceiq.customer.id",
        "traceiq.customer.name",
        "traceiq.ingest_source",
        "traceiq.step_type",
        "traceiq.modality",
        "traceiq.trace.root",
        "traceiq.usage.cache_read_tokens",
        "traceiq.usage.cache_write_tokens",
        "traceiq.usage.audio_input_tokens",
        "traceiq.usage.audio_output_tokens",
        "traceiq.usage.vision_tokens",
        "traceiq.usage.input_audio_ms",
        "traceiq.usage.output_audio_ms",
        "traceiq.usage.input_characters",
        "traceiq.usage.image_count",
        "traceiq.user.email",
    }
)

GEN_AI_ALLOWLIST = frozenset(
    {
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.tool.name",
        "gen_ai.operation.name",
        "gen_ai.request.temperature",
    }
)


def strip_content_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    """Never export prompt/completion bodies (privacy / spec)."""
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        low = key.lower()
        if low.startswith("gen_ai.prompt") or low.startswith("gen_ai.completion"):
            continue
        if low.startswith("llm.prompts") or low.startswith("llm.completions"):
            continue
        if low.endswith(".content") and "usage" not in low:
            continue
        out[key] = value
    return out


def enrich_attributes(
    raw: dict[str, Any], *, merge_request_context: bool = True
) -> dict[str, Any]:
    """
    Apply §3 enrichment. Never adds illicit traceiq.* keys.

    merge_request_context=False at export time — batch exporter threads must not
    re-read ContextVar (would tag wrong request). Spans are stamped on_start /
    decorator exit instead.
    """
    attrs = strip_content_attributes(dict(raw))

    if merge_request_context:
        for key, value in merged_trace_attrs().items():
            if key in attrs and attrs[key] not in (None, ""):
                continue
            attrs[key] = value

    normalize_tokens(attrs)
    ensure_model(attrs)
    ensure_provider(attrs)

    step = infer_step_type(attrs)
    if step:
        attrs[ATTR_STEP_TYPE] = step

    attrs[ATTR_MODALITY] = infer_modality(attrs)

    for key, value in extract_cache_usage(attrs).items():
        attrs[key] = value
    for key, value in extract_audio_vision_usage(attrs).items():
        attrs[key] = value

    attrs["traceiq.ingest_source"] = "sdk"

    for k in [k for k in attrs if k.startswith("traceiq.") and k not in TRACEIQ_ALLOWLIST]:
        del attrs[k]

    return strip_content_attributes(attrs)


def filter_for_export(attrs: dict[str, Any]) -> dict[str, Any]:
    """
    Defense-in-depth for every export mode: TraceIQ allowlist + safe gen_ai only.

    Drops prompt/completion content even if an instrumentor added it.
    """
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key.startswith("traceiq.") and key in TRACEIQ_ALLOWLIST:
            out[key] = value
        elif key in GEN_AI_ALLOWLIST:
            out[key] = value
        # Keep a few non-content instrumentation keys useful for debugging
        elif key in ("gen_ai.operation.name", "gen_ai.request.temperature"):
            out[key] = value
    return out


# Back-compat name used by older call sites / tests
filter_for_spans_json = filter_for_export


class LeanEnricher(SpanProcessor):
    """Stamp process/request context as soon as a span starts (writable)."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        for key, value in merged_trace_attrs().items():
            if key not in (span.attributes or {}):
                span.set_attribute(key, value)
        span.set_attribute("traceiq.ingest_source", "sdk")

    def on_end(self, span: ReadableSpan) -> None:
        return

    def shutdown(self) -> None:
        return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class EnrichingSpanExporter(SpanExporter):
    """
    Wrap exporter: normalize + strip content before send.

    Does not re-merge ContextVar (batch thread safety).
    """

    def __init__(self, inner: SpanExporter, *, spans_json_filter: bool = False) -> None:
        self._inner = inner
        # Always filter to allowlist for privacy; flag kept for API compat.
        del spans_json_filter
        self._spans_json_filter = True

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        enriched: list[ReadableSpan] = []
        for span in spans:
            enriched.append(_span_with_attrs(span))
        try:
            return self._inner.export(enriched)
        except Exception:
            import logging

            logging.getLogger("traceiq").exception("span export failed")
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _span_with_attrs(span: ReadableSpan) -> ReadableSpan:
    raw = dict(span.attributes or {})
    # No ContextVar merge here — only normalize + privacy filter.
    enriched = enrich_attributes(raw, merge_request_context=False)
    enriched = filter_for_export(enriched)

    attrs_obj = getattr(span, "_attributes", None)
    if isinstance(attrs_obj, dict):
        attrs_obj.clear()
        attrs_obj.update(enriched)
        return span

    try:
        mutable = dict(attrs_obj) if attrs_obj is not None else {}
        mutable.clear()
        mutable.update(enriched)
        object.__setattr__(span, "_attributes", mutable)
    except Exception:
        pass
    return span
