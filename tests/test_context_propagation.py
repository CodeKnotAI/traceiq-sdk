"""ContextVar propagation and set_context allowlist."""

import asyncio

import pytest

from traceiq._context import (
    clear_context,
    configure_globals,
    get_request_context,
    merged_trace_attrs,
    set_context,
)


def test_set_context_and_merged_attrs():
    configure_globals(app_name="app", environment="prod")
    clear_context()
    set_context(workflow_id="w1", agent_name="a1", product_id="p1")
    attrs = merged_trace_attrs()
    assert attrs["traceiq.workflow_id"] == "w1"
    assert attrs["traceiq.agent_name"] == "a1"
    assert attrs["traceiq.product.id"] == "p1"
    assert attrs["traceiq.app_name"] == "app"
    clear_context()


def test_set_context_rejects_unknown():
    with pytest.raises(TypeError, match="Unknown"):
        set_context(tenant_id="x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_context_propagates_asyncio():
    configure_globals(app_name="app", environment="prod")
    clear_context()
    set_context(workflow_id="async-wf")

    async def child():
        return get_request_context().workflow_id

    assert await child() == "async-wf"
    clear_context()
