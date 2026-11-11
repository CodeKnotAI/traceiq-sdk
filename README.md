# TraceIQ SDK (`traceiq-sdk`)

See what your AI agents cost: per run, agent, customer and person. OpenTelemetry-native, with a locked attribute contract (no field sprawl). Sends model names, token counts and the labels you set, never prompts or answers.

Install name: **`traceiq-sdk`**. Import: **`import traceiq`**. Docs: [traceiq.gitbook.io/traceiq-docs](https://traceiq.gitbook.io/traceiq-docs).

> **Upgrading from 0.2.x:** 0.3 is a new SDK. It sends OpenTelemetry to `{endpoint}/v1/otlp/v1/traces` and replaces the 0.2 options (`batch_send`, the `/v1/traces` endpoint). Get a fresh ingest key in TraceIQ and follow the Quickstart below.

## Install

```bash
pip install traceiq-sdk                 # core
pip install "traceiq-sdk[openai]"       # OpenAI auto-instrumentation
pip install "traceiq-sdk[anthropic]"
pip install "traceiq-sdk[langchain]"    # LangChain / LangGraph
pip install "traceiq-sdk[llamaindex]"
pip install "traceiq-sdk[all]"
```

## Quickstart

Set env (optional for local file export):

```bash
export TRACEIQ_API_KEY=...
export TRACEIQ_ENDPOINT=https://api.traceiq.dev   # omit → ./traces/
export TRACEIQ_APP_NAME=support-agent-api         # optional
export TRACEIQ_ENVIRONMENT=production             # optional
```

```python
import traceiq

traceiq.init()

# Existing OpenAI / LangChain / Anthropic / LlamaIndex code unchanged.
# Installed extras are auto-instrumented on init — no decorators required.
```

No `TRACEIQ_ENDPOINT` → spans written under `./traces/` for local debug. Batch export every **5s**; process exit flushes automatically (`flush()` is only needed in short scripts/tests).

## Optional: agent trees and attribution

Use decorators when you want a run root and step types. Use `set_context` when you want product / project / agent / customer rollups.

```python
from traceiq import workflow, set_context

@workflow(name="triage_ticket")
def handle(ticket_id: str, user_msg: str, account):
    set_context(
        agent_name="triage",
        product_name="Pro",
        customer_id=account.id,        # your B2B customer / tenant id
        customer_name=account.name,
    )
    return run_agent(user_msg)
```

`set_context` keys: `workflow_id`, `agent_name`, `product_id`, `product_name`, `project_id`, `project_name`, `customer_id`, `customer_name`, `user_email`.
`customer_id` links the run to a TraceIQ Customer (matched on the same id your revenue import uses), which powers AI cost vs revenue per customer.
`user_email` (internal agents) puts the run's spend on that employee, when the email matches someone in People & teams. Unknown emails are ignored; nobody is created.

New agents start **unclassified**: an admin marks each one as serving employees or customers on the Agents page before its spend shows on Employee or Customer spending. Until then it only counts in the company total and organization budget.

### Audio, TTS and images

Token usage is read automatically. For usage billed per minute, character or image, report it inside the call's span:

```python
traceiq.record_usage(input_audio_ms=42_000)      # speech-to-text
traceiq.record_usage(input_characters=1_200)     # text-to-speech
traceiq.record_usage(image_count=2)              # per-image vision
```

Calls TraceIQ has no rate card for are shown as unpriced volume on Overview, never as $0.

Also available: `@task`, `@tool`, `@agent`, `clear_context`, `scoped_context`.

### Web apps: clear attribution every request

`set_context` writes a process/thread ContextVar. LLM calls **outside** a decorator keep whatever was last set — so a bare `set_context(product_id=…)` can leak into later requests on the same worker. Wrap each request:

**Django**

```python
# middleware.py
from traceiq import clear_context

class TraceIQRequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_context()  # drop any leak from a prior request on this worker
        try:
            return self.get_response(request)
        finally:
            clear_context()
```

**FastAPI**

```python
from traceiq import clear_context

@app.middleware("http")
async def traceiq_context(request, call_next):
    clear_context()
    try:
        return await call_next(request)
    finally:
        clear_context()
```

`scoped_context(product_id=…)` is for a single block that must restore the previous snapshot. Prefer setting product/project inside `@workflow` / `@agent` so failed runs still get stamped.

## Budgets

If an admin sets an **enforce** budget on an agent in TraceIQ and it's used up,
`@workflow` / `@agent` raise `traceiq.BudgetExceededError` *before* running, so
no more money is spent until the budget window resets. Catch it to show a
friendly message:

```python
from traceiq import BudgetExceededError

try:
    handle(ticket)
except BudgetExceededError as exc:
    return "Our AI assistant is paused for now."  # exc.info has budget details
```

The SDK checks budget status at most once a minute (in the background after the
first check) and **fails open**: if TraceIQ can't be reached, runs continue.
Turn it off with `init(enforce_budgets=False)` or `TRACEIQ_ENFORCE_BUDGETS=0`.
Spend is always recorded either way.

## Frameworks

Install the matching extra; call `init()` once. LLM library calls emit child spans automatically.

| Stack | Extra |
|-------|-------|
| OpenAI | `[openai]` |
| Anthropic | `[anthropic]` |
| LangChain / LangGraph | `[langchain]` / `[langgraph]` |
| LlamaIndex | `[llamaindex]` |
| CrewAI | `[openai]` and/or `[langchain]` |

Decorators are optional — add `@workflow` on your entrypoint only if you want TraceIQ run identity around the call tree.

## Public API

`init`, `flush`, `set_context`, `clear_context`, `scoped_context`, `record_usage`, `@workflow`, `@task`, `@tool`, `@agent`, `BudgetExceededError`

## Export

- OTLP/HTTP JSON → `{endpoint}/v1/otlp/v1/traces` (Bearer, gzip). Only mode.
- Up to 3 attempts on network errors / 408 / 429 / 5xx; other 4xx are dropped and logged. Export never blocks your agent — it runs on the batch thread.
- Batch every **5s** (`disable_batch=True` for sync scripts)

## Attributes (locked)

Only allowlisted `traceiq.*` plus `gen_ai.system` / `gen_ai.request.model` / usage tokens. No prompt/completion content capture. No client-side pricing.

## Develop

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
