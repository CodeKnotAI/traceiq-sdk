"""Infer traceiq.modality from usage / request shape."""

from __future__ import annotations

from typing import Any, Mapping

ATTR_MODALITY = "traceiq.modality"


def infer_modality(attrs: Mapping[str, Any]) -> str:
    existing = attrs.get(ATTR_MODALITY)
    if existing:
        return str(existing)

    # Values match the backend rate-card modalities.
    has_vision = bool(
        attrs.get("traceiq.usage.vision_tokens")
        or attrs.get("traceiq.usage.image_count")
        or attrs.get("gen_ai.usage.image_tokens")
        or attrs.get("gen_ai.prompt.has_images")
    )
    audio_in = bool(
        attrs.get("traceiq.usage.audio_input_tokens")
        or attrs.get("traceiq.usage.input_audio_ms")
        or attrs.get("gen_ai.usage.input_audio_tokens")
    )
    audio_out = bool(
        attrs.get("traceiq.usage.audio_output_tokens")
        or attrs.get("traceiq.usage.output_audio_ms")
        or attrs.get("traceiq.usage.input_characters")
        or attrs.get("gen_ai.usage.output_audio_tokens")
    )
    if (has_vision and (audio_in or audio_out)) or (audio_in and audio_out):
        return "multimodal"
    if has_vision:
        return "vision"
    if audio_out:
        return "audio_tts"
    if audio_in:
        return "audio_stt"
    return "text"
