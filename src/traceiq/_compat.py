"""Normalize gen_ai.* token/model/provider attrs (read-only fallbacks)."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

ATTR_SYSTEM = "gen_ai.system"
ATTR_REQUEST_MODEL = "gen_ai.request.model"
ATTR_RESPONSE_MODEL = "gen_ai.response.model"
ATTR_INPUT_TOKENS = "gen_ai.usage.input_tokens"
ATTR_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
ATTR_PROMPT_TOKENS = "gen_ai.usage.prompt_tokens"
ATTR_COMPLETION_TOKENS = "gen_ai.usage.completion_tokens"
ATTR_PROVIDER_NAME = "gen_ai.provider.name"

# Cache key variants seen in the wild
CACHE_READ_CANDIDATES = (
    "gen_ai.usage.cache_read_input_tokens",
    "gen_ai.usage.cache_read_tokens",
    "llm.usage.cache_read_input_tokens",
)
CACHE_WRITE_CANDIDATES = (
    "gen_ai.usage.cache_creation_input_tokens",
    "gen_ai.usage.cache_write_tokens",
    "llm.usage.cache_creation_input_tokens",
)

_MODEL_PREFIX_TO_SYSTEM = (
    (("gpt-", "o1", "o3", "text-embedding", "whisper", "tts-"), "openai"),
    (("claude-",), "anthropic"),
    (("gemini-",), "google"),
)


def _get(attrs: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return attrs[key]
    return None


def normalize_tokens(attrs: MutableMapping[str, Any]) -> None:
    """prompt/completion → input/output tokens."""
    if ATTR_INPUT_TOKENS not in attrs:
        legacy = _get(attrs, ATTR_PROMPT_TOKENS, "llm.usage.prompt_tokens")
        if legacy is not None:
            attrs[ATTR_INPUT_TOKENS] = int(legacy)
    if ATTR_OUTPUT_TOKENS not in attrs:
        legacy = _get(attrs, ATTR_COMPLETION_TOKENS, "llm.usage.completion_tokens")
        if legacy is not None:
            attrs[ATTR_OUTPUT_TOKENS] = int(legacy)


def ensure_model(attrs: MutableMapping[str, Any]) -> None:
    if ATTR_REQUEST_MODEL not in attrs or not attrs[ATTR_REQUEST_MODEL]:
        resp = _get(attrs, ATTR_RESPONSE_MODEL, "llm.request.model", "llm.model_name")
        if resp:
            attrs[ATTR_REQUEST_MODEL] = str(resp)


def ensure_provider(attrs: MutableMapping[str, Any]) -> None:
    if attrs.get(ATTR_SYSTEM):
        return
    provider = _get(attrs, ATTR_PROVIDER_NAME)
    if provider:
        attrs[ATTR_SYSTEM] = str(provider)
        return
    model = str(attrs.get(ATTR_REQUEST_MODEL) or "")
    lower = model.lower()
    for prefixes, system in _MODEL_PREFIX_TO_SYSTEM:
        if any(lower.startswith(p) for p in prefixes):
            attrs[ATTR_SYSTEM] = system
            return


def extract_cache_usage(attrs: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in CACHE_READ_CANDIDATES:
        if key in attrs and attrs[key] is not None:
            out["traceiq.usage.cache_read_tokens"] = int(attrs[key])
            break
    for key in CACHE_WRITE_CANDIDATES:
        if key in attrs and attrs[key] is not None:
            out["traceiq.usage.cache_write_tokens"] = int(attrs[key])
            break
    return out


def extract_audio_vision_usage(attrs: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    audio_in = _get(
        attrs,
        "gen_ai.usage.input_audio_tokens",
        "traceiq.usage.audio_input_tokens",
    )
    audio_out = _get(
        attrs,
        "gen_ai.usage.output_audio_tokens",
        "traceiq.usage.audio_output_tokens",
    )
    vision = _get(
        attrs,
        "gen_ai.usage.image_tokens",
        "llm.usage.image_tokens",
        "traceiq.usage.vision_tokens",
    )
    if audio_in is not None:
        out["traceiq.usage.audio_input_tokens"] = int(audio_in)
    if audio_out is not None:
        out["traceiq.usage.audio_output_tokens"] = int(audio_out)
    if vision is not None:
        out["traceiq.usage.vision_tokens"] = int(vision)
    return out
