"""Budget enforcement: blocked agents can't start a run; TraceIQ outages fail open."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from traceiq import BudgetExceededError, _enforcement, workflow
from traceiq._context import configure_globals
from traceiq._ids import stable_workflow_id


class _StatusServer:
    def __init__(self, blocked):
        self.blocked = blocked
        self.hits = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                body = json.dumps({"blocked_agents": outer.blocked, "ttl_seconds": 60}).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    srv = _StatusServer(
        [{
            "app_name": "support", "workflow_id": stable_workflow_id("triage"),
            "environment": "production", "budget": "Triage cap",
            "amount_usd": "50", "spent_usd": "51.20", "resets_at": "2026-11-01T00:00:00+00:00",
        }]
    )
    configure_globals(app_name="support", environment="production", api_key="tiq_x", endpoint=srv.origin)
    _enforcement.configure(True)
    yield srv
    srv.close()
    _enforcement.configure(True)


def test_blocked_workflow_raises_before_running(server):
    ran = []

    @workflow(name="triage")
    def triage():
        ran.append(1)

    with pytest.raises(BudgetExceededError) as exc:
        triage()
    assert ran == []
    assert "Triage cap" in str(exc.value)


def test_other_workflows_run_and_status_is_cached(server):
    @workflow(name="billing")
    def billing():
        return "ok"

    assert billing() == "ok"
    assert billing() == "ok"
    assert server.hits == 1  # cached for ttl_seconds


def test_unreachable_traceiq_fails_open():
    configure_globals(app_name="support", environment="production", api_key="tiq_x", endpoint="http://127.0.0.1:9")
    _enforcement.configure(True)

    @workflow(name="triage")
    def triage():
        return "ran"

    assert triage() == "ran"


def test_disabled_never_checks(server):
    _enforcement.configure(False)

    @workflow(name="triage")
    def triage():
        return "ran"

    assert triage() == "ran"
    assert server.hits == 0
