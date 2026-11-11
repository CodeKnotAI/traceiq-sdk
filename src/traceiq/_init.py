"""traceiq.init / flush — TracerProvider, instrumentations, exporters."""

from __future__ import annotations

import atexit
import importlib
import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from traceiq import _enforcement
from traceiq._context import configure_globals, get_globals
from traceiq._enrich import EnrichingSpanExporter, LeanEnricher
from traceiq._exporter import (
    FileSpanExporter,
    OTLPJsonSpanExporter,
)

logger = logging.getLogger("traceiq")

FLUSH_INTERVAL_MS = 5000
MAX_EXPORT_BATCH_SIZE = 512

_provider: TracerProvider | None = None
_atexit_registered = False
_misconfig_warned = False


def _instrument_installed(provider: TracerProvider) -> None:
    """
    Bind framework instrumentors to *our* TracerProvider.

    Without tracer_provider=, LLM spans can attach to Datadog/Honeycomb's
    global provider and never reach TraceIQ.
    """
    for mod, starter in [
        ("opentelemetry.instrumentation.openai", "OpenAIInstrumentor"),
        ("opentelemetry.instrumentation.anthropic", "AnthropicInstrumentor"),
        ("opentelemetry.instrumentation.langchain", "LangchainInstrumentor"),
        ("opentelemetry.instrumentation.llamaindex", "LlamaIndexInstrumentor"),
    ]:
        try:
            m = importlib.import_module(mod)
            instrumentor = getattr(m, starter)()
            already = getattr(
                instrumentor, "is_instrumented_by_opentelemetry", False
            )
            if already:
                logger.warning(
                    "%s already instrumented by another library — "
                    "TraceIQ may receive no LLM spans from it",
                    starter,
                )
            try:
                instrumentor.instrument(tracer_provider=provider)
            except TypeError:
                instrumentor.instrument()
            logger.debug("instrumented %s", starter)
        except Exception:
            continue


def _build_exporter(
    *,
    endpoint: str,
    api_key: str,
    export_mode: str,
    service_name: str = "traceiq-app",
) -> SpanExporter:
    if not endpoint:
        return FileSpanExporter("./traces")
    if export_mode != "otlp":
        logger.warning(
            "export_mode=%r is not supported; using OTLP/HTTP JSON", export_mode
        )
    return OTLPJsonSpanExporter(endpoint, api_key, service_name=service_name)


def init(
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    app_name: str | None = None,
    environment: str | None = None,
    export_mode: str = "otlp",
    disable_batch: bool = False,
    exporter: SpanExporter | None = None,
    enforce_budgets: bool | None = None,
) -> None:
    """
    Configure TracerProvider, LeanEnricher, batch export, and installed OTel extras.

    Zero-arg happy path: reads TRACEIQ_API_KEY, TRACEIQ_ENDPOINT, TRACEIQ_APP_NAME,
    TRACEIQ_ENVIRONMENT from the environment. Empty endpoint → ./traces/ file export.
    """
    global _provider, _atexit_registered, _misconfig_warned

    key = api_key if api_key is not None else os.environ.get("TRACEIQ_API_KEY", "")
    ep = endpoint if endpoint is not None else os.environ.get("TRACEIQ_ENDPOINT", "")
    name = (
        app_name
        if app_name is not None
        else os.environ.get("TRACEIQ_APP_NAME", "traceiq-app")
    ) or "traceiq-app"
    env = (
        environment
        if environment is not None
        else os.environ.get("TRACEIQ_ENVIRONMENT", "")
    )

    if ep and not key and not _misconfig_warned:
        logger.warning(
            "TRACEIQ_ENDPOINT is set but TRACEIQ_API_KEY is empty — "
            "OTLP export will likely be rejected"
        )
        _misconfig_warned = True
    if not ep and exporter is None:
        logger.info("No TRACEIQ_ENDPOINT — writing spans to ./traces/")

    # Enforce budgets by default (TRACEIQ_ENFORCE_BUDGETS=0 to turn off).
    if enforce_budgets is None:
        enforce_budgets = os.environ.get("TRACEIQ_ENFORCE_BUDGETS", "1").strip().lower() not in ("0", "false", "no")
    _enforcement.configure(enforce_budgets)

    configure_globals(
        app_name=name,
        environment=env,
        api_key=key,
        endpoint=ep,
        export_mode=export_mode,
        disable_batch=disable_batch,
    )

    resource = Resource.create({"service.name": name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(LeanEnricher())

    inner = exporter or _build_exporter(
        endpoint=ep,
        api_key=key,
        export_mode=export_mode,
        service_name=name,
    )
    # Always run enrichment before the concrete exporter
    wrapped = EnrichingSpanExporter(inner)

    if disable_batch:
        provider.add_span_processor(SimpleSpanProcessor(wrapped))
    else:
        provider.add_span_processor(
            BatchSpanProcessor(
                wrapped,
                schedule_delay_millis=FLUSH_INTERVAL_MS,
                max_export_batch_size=MAX_EXPORT_BATCH_SIZE,
            )
        )

    trace.set_tracer_provider(provider)
    # set_tracer_provider often no-ops (logs) instead of raising when a
    # provider already exists — detect that explicitly (R4).
    if trace.get_tracer_provider() is not provider:
        logger.warning(
            "Global TracerProvider is not TraceIQ's — another OTel stack may "
            "already own it. Instrumentors still bind to TraceIQ's provider."
        )
    _provider = provider

    _instrument_installed(provider)

    if not _atexit_registered:
        atexit.register(_atexit_flush)
        _atexit_registered = True


def flush(timeout_millis: int = 10_000) -> bool:
    if _provider is None:
        return True
    return _provider.force_flush(timeout_millis)


def _atexit_flush() -> None:
    try:
        flush()
        if _provider is not None:
            _provider.shutdown()
    except Exception:
        pass


def get_provider() -> TracerProvider | None:
    return _provider
