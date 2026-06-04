"""Observability and tracing via Langfuse.

Langfuse records every model and tool call as a structured trace (inputs, outputs,
latency, tokens, cost). We hand a Langfuse callback handler to LangChain/LangGraph; it
then captures the whole report-generation tree without any code in the business logic.

If no Langfuse keys are configured, get_callbacks() returns [] and everything still runs
normally — tracing is strictly optional.
"""

from __future__ import annotations

from functools import lru_cache

from src.config import get_settings


@lru_cache(maxsize=1)
def _handler():
    """Build (once) the Langfuse callback handler, or None if Langfuse is not configured."""
    s = get_settings()
    if not s.langfuse_enabled:
        return None
    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
    except Exception:  # noqa: BLE001 - never let tracing break the app
        return None


def get_callbacks() -> list:
    """Return LangChain callbacks (the Langfuse handler) if available, else []."""
    h = _handler()
    return [h] if h is not None else []
