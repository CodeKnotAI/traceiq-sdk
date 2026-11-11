"""Report billable non-token usage (audio minutes, TTS characters, images)."""

from __future__ import annotations

from opentelemetry import trace

_KEYS = {
    "input_audio_ms": "traceiq.usage.input_audio_ms",
    "output_audio_ms": "traceiq.usage.output_audio_ms",
    "input_characters": "traceiq.usage.input_characters",
    "image_count": "traceiq.usage.image_count",
}


def record_usage(
    *,
    input_audio_ms: int | None = None,
    output_audio_ms: int | None = None,
    input_characters: int | None = None,
    image_count: int | None = None,
) -> None:
    """
    Attach usage that providers bill per minute / character / image to the
    current span, so TraceIQ can price it (e.g. after a Whisper or TTS call):

        traceiq.record_usage(input_audio_ms=42_000)
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return
    values = {
        "input_audio_ms": input_audio_ms,
        "output_audio_ms": output_audio_ms,
        "input_characters": input_characters,
        "image_count": image_count,
    }
    for name, value in values.items():
        if value is not None and int(value) >= 0:
            span.set_attribute(_KEYS[name], int(value))
