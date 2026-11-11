"""Decorator span kinds and nesting."""

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import traceiq
from traceiq import agent, task, tool, workflow
from traceiq._ids import stable_workflow_id
from traceiq._init import get_provider


def _setup():
    exporter = InMemorySpanExporter()
    traceiq.init(
        app_name="test-app",
        environment="test",
        endpoint="",
        disable_batch=True,
        exporter=exporter,
    )
    return exporter


def test_workflow_sets_root_and_workflow_id():
    exporter = _setup()

    @workflow(name="triage_ticket")
    def handle():
        return 1

    assert handle() == 1
    traceiq.flush()
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("traceiq.step_type") == "workflow"
    assert attrs.get("traceiq.trace.root") is True
    assert attrs.get("traceiq.workflow_id") == stable_workflow_id("triage_ticket")
    assert attrs.get("traceiq.app_name") == "test-app"
    assert attrs.get("traceiq.ingest_source") == "sdk"


def test_nested_task_tool_agent():
    exporter = _setup()

    @workflow(name="run")
    def handle():
        @task(name="step")
        def inner():
            @tool(name="search")
            def t():
                return "ok"

            return t()

        @agent(name="triage")
        def ag():
            return 2

        return inner(), ag()

    handle()
    traceiq.flush()
    kinds = {
        s.name: dict(s.attributes or {}).get("traceiq.step_type")
        for s in exporter.get_finished_spans()
    }
    assert kinds["run"] == "workflow"
    assert kinds["step"] == "task"
    assert kinds["search"] == "tool"
    assert kinds["triage"] == "agent"


def test_async_workflow():
    exporter = _setup()

    @workflow(name="async_run")
    async def handle():
        return 42

    import asyncio

    assert asyncio.run(handle()) == 42
    traceiq.flush()
    assert any(s.name == "async_run" for s in exporter.get_finished_spans())
