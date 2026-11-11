"""Person email, multimodal units and modality values match the backend contract."""

from opentelemetry.sdk.trace import TracerProvider

import traceiq
from traceiq._context import clear_context, configure_globals, set_context
from traceiq._enrich import enrich_attributes, filter_for_export
from traceiq._modality import infer_modality


def test_user_email_is_stamped_lowercased_and_exported():
    configure_globals(app_name="app", environment="prod")
    set_context(user_email="Dev@Acme.com")
    out = filter_for_export(enrich_attributes({}))
    assert out["traceiq.user.email"] == "dev@acme.com"
    clear_context()


def test_modality_uses_backend_values():
    assert infer_modality({"traceiq.usage.input_audio_ms": 1000}) == "audio_stt"
    assert infer_modality({"gen_ai.usage.output_audio_tokens": 5}) == "audio_tts"
    assert infer_modality({"traceiq.usage.input_characters": 50}) == "audio_tts"
    assert infer_modality({"traceiq.usage.image_count": 1}) == "vision"
    assert infer_modality({"traceiq.usage.image_count": 1, "traceiq.usage.input_audio_ms": 1}) == "multimodal"
    assert infer_modality({}) == "text"


def test_record_usage_sets_allowlisted_attrs_on_current_span():
    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("stt") as span:
        traceiq.record_usage(input_audio_ms=42_000, image_count=None)
    attrs = dict(span.attributes or {})
    assert attrs["traceiq.usage.input_audio_ms"] == 42_000
    assert "traceiq.usage.image_count" not in attrs
    out = filter_for_export(enrich_attributes(attrs, merge_request_context=False))
    assert out["traceiq.usage.input_audio_ms"] == 42_000
    assert out["traceiq.modality"] == "audio_stt"
