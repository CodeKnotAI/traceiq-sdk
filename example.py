"""Manual example — init-only happy path (no decorators required).

Uses OpenAI if OPENAI_API_KEY is set; otherwise emits a fake LLM span.
Unset TRACEIQ_ENDPOINT → spans land in ./traces/
"""

from __future__ import annotations

import os

import traceiq


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say hi in one word."}],
        )
        print("openai:", resp.choices[0].message.content)
    else:
        from opentelemetry import trace

        tracer = trace.get_tracer("demo")
        with tracer.start_as_current_span("fake_llm") as span:
            span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            span.set_attribute("gen_ai.usage.input_tokens", 5)
            span.set_attribute("gen_ai.usage.output_tokens", 1)
            span.set_attribute("gen_ai.system", "openai")
        print("no OPENAI_API_KEY — emitted fake_llm span")


if __name__ == "__main__":
    # Zero-arg init: env TRACEIQ_* or local ./traces/ when endpoint unset.
    # disable_batch so this short script writes spans before exit.
    os.environ.setdefault("TRACEIQ_APP_NAME", "sdk-example")
    os.environ.setdefault("TRACEIQ_ENVIRONMENT", "dev")
    traceiq.init(disable_batch=True)
    main()
    # Optional upgrades: @workflow / set_context for run trees & attribution.
    print("done — check ./traces/ if TRACEIQ_ENDPOINT is unset")
