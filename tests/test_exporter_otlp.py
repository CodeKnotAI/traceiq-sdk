"""Exporter URL helpers and OTLP payload shape."""

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from traceiq._context import configure_globals
from traceiq._exporter import normalize_otlp_endpoint, readable_span_to_otlp


def test_normalize_otlp_endpoint():
    assert normalize_otlp_endpoint("https://api.example.com").endswith(
        "/v1/otlp/v1/traces"
    )
    assert (
        normalize_otlp_endpoint("https://api.example.com/v1/otlp/v1/traces")
        == "https://api.example.com/v1/otlp/v1/traces"
    )


def test_otlp_payload():
    configure_globals(app_name="app", environment="prod")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("llm") as span:
        span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
        span.set_attribute("gen_ai.usage.input_tokens", 3)
        span.set_attribute("gen_ai.usage.output_tokens", 1)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    otlp = readable_span_to_otlp(spans[0])
    assert "traceId" in otlp and "spanId" in otlp
    keys = {a["key"] for a in otlp["attributes"]}
    assert "traceiq.ingest_source" in keys
    assert "gen_ai.request.model" in keys

    provider.shutdown()
