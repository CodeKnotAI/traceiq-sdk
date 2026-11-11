"""TraceIQ Capture — OpenTelemetry instrumentation with a locked attribute contract."""

from traceiq._context import clear_context, scoped_context, set_context
from traceiq._enforcement import BudgetExceededError
from traceiq._init import flush, init
from traceiq._usage import record_usage
from traceiq.decorators import agent, task, tool, workflow

__all__ = [
    "init",
    "flush",
    "set_context",
    "clear_context",
    "scoped_context",
    "workflow",
    "task",
    "tool",
    "agent",
    "BudgetExceededError",
    "record_usage",
]
__version__ = "0.3.0"
