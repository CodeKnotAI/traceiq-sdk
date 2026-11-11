"""Infer traceiq.step_type from decorator marks or span attrs."""

from __future__ import annotations

from typing import Any, Mapping

ATTR_STEP_TYPE = "traceiq.step_type"


def infer_step_type(attrs: Mapping[str, Any]) -> str | None:
    existing = attrs.get(ATTR_STEP_TYPE)
    if existing:
        return str(existing)

    # Tool signals from instrumentations
    if attrs.get("gen_ai.tool.name") or attrs.get("traceloop.entity.name") == "tool":
        return "tool"

    # LLM signals
    if (
        attrs.get("gen_ai.request.model")
        or attrs.get("gen_ai.usage.input_tokens") is not None
        or attrs.get("gen_ai.usage.prompt_tokens") is not None
    ):
        return "llm"

    return None
