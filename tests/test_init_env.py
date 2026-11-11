"""Zero-arg init from env + misconfig warning."""

from __future__ import annotations

import logging

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import traceiq
from traceiq import _init as init_mod
from traceiq._context import get_globals


def _reset_misconfig_flag() -> None:
    init_mod._misconfig_warned = False


def test_init_reads_env(monkeypatch):
    monkeypatch.setenv("TRACEIQ_API_KEY", "tk_test")
    monkeypatch.setenv("TRACEIQ_ENDPOINT", "https://example.test")
    monkeypatch.setenv("TRACEIQ_APP_NAME", "env-app")
    monkeypatch.setenv("TRACEIQ_ENVIRONMENT", "staging")
    _reset_misconfig_flag()

    exporter = InMemorySpanExporter()
    traceiq.init(disable_batch=True, exporter=exporter)

    g = get_globals()
    assert g.api_key == "tk_test"
    assert g.endpoint == "https://example.test"
    assert g.app_name == "env-app"
    assert g.environment == "staging"
    assert g.initialized is True


def test_init_warns_when_endpoint_without_key(monkeypatch, caplog):
    monkeypatch.delenv("TRACEIQ_API_KEY", raising=False)
    monkeypatch.setenv("TRACEIQ_ENDPOINT", "https://example.test")
    monkeypatch.delenv("TRACEIQ_APP_NAME", raising=False)
    _reset_misconfig_flag()

    exporter = InMemorySpanExporter()
    with caplog.at_level(logging.WARNING, logger="traceiq"):
        traceiq.init(api_key="", disable_batch=True, exporter=exporter)

    assert any(
        "TRACEIQ_API_KEY is empty" in r.message for r in caplog.records
    )

    # Once per process
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="traceiq"):
        traceiq.init(api_key="", disable_batch=True, exporter=exporter)
    assert not any(
        "TRACEIQ_API_KEY is empty" in r.message for r in caplog.records
    )
