"""Token/model/provider normalization."""

from traceiq._compat import ensure_model, ensure_provider, normalize_tokens


def test_normalize_prompt_completion_tokens():
    attrs = {
        "gen_ai.usage.prompt_tokens": 11,
        "gen_ai.usage.completion_tokens": 7,
    }
    normalize_tokens(attrs)
    assert attrs["gen_ai.usage.input_tokens"] == 11
    assert attrs["gen_ai.usage.output_tokens"] == 7


def test_ensure_model_from_response():
    attrs = {"gen_ai.response.model": "claude-sonnet-4-5"}
    ensure_model(attrs)
    assert attrs["gen_ai.request.model"] == "claude-sonnet-4-5"
    ensure_provider(attrs)
    assert attrs["gen_ai.system"] == "anthropic"
