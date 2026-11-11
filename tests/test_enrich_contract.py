"""Contract: only allowlisted traceiq.* keys after enrich."""

from traceiq._context import clear_context, configure_globals, set_context
from traceiq._enrich import TRACEIQ_ALLOWLIST, enrich_attributes


def test_enrich_only_allowlisted_traceiq_keys():
    configure_globals(app_name="app", environment="prod")
    set_context(
        workflow_id="wf1",
        agent_name="triage",
        product_id="p1",
        product_name="Pro",
        project_id="pr1",
        project_name="Support",
    )
    raw = {
        "gen_ai.usage.prompt_tokens": 10,
        "gen_ai.usage.completion_tokens": 5,
        "gen_ai.response.model": "gpt-4o-mini",
        "traceiq.evil": "nope",
        "gen_ai.usage.cache_read_input_tokens": 3,
    }
    out = enrich_attributes(raw)
    for key in out:
        if key.startswith("traceiq."):
            assert key in TRACEIQ_ALLOWLIST, key
    assert "traceiq.evil" not in out
    assert out["traceiq.ingest_source"] == "sdk"
    assert out["traceiq.app_name"] == "app"
    assert out["traceiq.environment"] == "prod"
    assert out["traceiq.workflow_id"] == "wf1"
    assert out["gen_ai.usage.input_tokens"] == 10
    assert out["gen_ai.usage.output_tokens"] == 5
    assert out["gen_ai.request.model"] == "gpt-4o-mini"
    assert out["gen_ai.system"] == "openai"
    assert out["traceiq.step_type"] == "llm"
    assert out["traceiq.modality"] == "text"
    assert out["traceiq.usage.cache_read_tokens"] == 3
    clear_context()
