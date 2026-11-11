"""B2/B3: content strip on export path; decorator restores context."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from traceiq import agent, init, set_context, workflow
from traceiq._context import clear_context, get_request_context
from traceiq._enrich import enrich_attributes, filter_for_export, strip_content_attributes
from traceiq._init import flush


def test_strip_prompt_content():
    raw = {
        "gen_ai.prompt.0.content": "SECRET",
        "gen_ai.completion.0.content": "ALSO SECRET",
        "gen_ai.usage.input_tokens": 3,
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-4o-mini",
    }
    cleaned = strip_content_attributes(raw)
    assert "gen_ai.prompt.0.content" not in cleaned
    assert "gen_ai.completion.0.content" not in cleaned
    assert cleaned["gen_ai.usage.input_tokens"] == 3

    exported = filter_for_export(enrich_attributes(raw, merge_request_context=False))
    assert "gen_ai.prompt.0.content" not in exported
    assert exported.get("gen_ai.usage.input_tokens") == 3


def test_agent_decorator_restores_context():
    clear_context()
    set_context(product_id="before")

    mem = InMemorySpanExporter()
    init(endpoint="", disable_batch=True, exporter=mem)

    @agent(name="temp-agent")
    def run():
        assert get_request_context().agent_name == "temp-agent"
        return 1

    assert run() == 1
    # After decorator exit, agent_name must not leak
    assert get_request_context().agent_name == ""
    assert get_request_context().product_id == "before"
    flush()
    clear_context()


def test_workflow_stamps_product_set_inside():
    clear_context()
    mem = InMemorySpanExporter()
    init(endpoint="", disable_batch=True, exporter=mem)

    @workflow(name="inner-product")
    def run():
        set_context(product_id="prod-99", product_name="Widget")
        return "ok"

    assert run() == "ok"
    flush()
    spans = mem.get_finished_spans()
    assert spans
    root = spans[-1]
    attrs = dict(root.attributes or {})
    assert attrs.get("traceiq.product.id") == "prod-99"
    clear_context()
