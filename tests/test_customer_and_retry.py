"""customer_* context (B6) + exporter gzip / bounded retry."""

import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from urllib.error import HTTPError

from traceiq import _exporter
from traceiq._context import clear_context, merged_trace_attrs, set_context
from traceiq._enrich import TRACEIQ_ALLOWLIST


def test_customer_context_stamped_and_allowlisted():
    clear_context()
    set_context(customer_id="acme-123", customer_name="Acme")
    attrs = merged_trace_attrs()
    assert attrs["traceiq.customer.id"] == "acme-123"
    assert attrs["traceiq.customer.name"] == "Acme"
    assert {"traceiq.customer.id", "traceiq.customer.name"} <= TRACEIQ_ALLOWLIST
    clear_context()
    assert "traceiq.customer.id" not in merged_trace_attrs()


class _Server:
    """Local HTTP server replying with a scripted list of status codes."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.bodies = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["content-length"]))
                outer.bodies.append((self.headers.get("content-encoding"), raw))
                code = outer.statuses.pop(0) if outer.statuses else 200
                self.send_response(code)
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1/otlp/v1/traces"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_exporter.time, "sleep", lambda s: None)


def test_gzip_body_and_retry_on_503():
    srv = _Server([503, 200])
    try:
        _exporter._post_json(srv.url, "key", {"resourceSpans": []})
    finally:
        srv.close()
    assert len(srv.bodies) == 2
    encoding, raw = srv.bodies[-1]
    assert encoding == "gzip"
    assert json.loads(gzip.decompress(raw)) == {"resourceSpans": []}


def test_no_retry_on_401():
    srv = _Server([401, 200])
    try:
        with pytest.raises(HTTPError):
            _exporter._post_json(srv.url, "bad", {"resourceSpans": []})
    finally:
        srv.close()
    assert len(srv.bodies) == 1


def test_gives_up_after_max_attempts():
    srv = _Server([503] * 10)
    try:
        with pytest.raises(HTTPError):
            _exporter._post_json(srv.url, "key", {"resourceSpans": []})
    finally:
        srv.close()
    assert len(srv.bodies) == _exporter.MAX_ATTEMPTS
