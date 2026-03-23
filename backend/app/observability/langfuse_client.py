"""Langfuse client — optional tracing; no-op when credentials not configured."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_LANGFUSE_CLIENT: Any = None


def get_langfuse_client(settings: Settings | None = None) -> Any | None:
    """
    Return Langfuse client if configured; otherwise None.
    Uses singleton to avoid repeated initialization.
    """
    global _LANGFUSE_CLIENT
    s = settings or get_settings()
    if not s.langfuse_enabled:
        return None
    if _LANGFUSE_CLIENT is None:
        try:
            from langfuse import Langfuse

            _LANGFUSE_CLIENT = Langfuse(
                public_key=s.langfuse_public_key,
                secret_key=s.langfuse_secret_key,
                host=s.langfuse_host,
            )
            logger.info("Langfuse client initialized")
        except Exception as e:
            logger.warning("Langfuse init failed: %s — tracing disabled", e)
            return None
    return _LANGFUSE_CLIENT


@contextmanager
def trace_chat_request(
    input_query: str,
    metadata: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """
    Context manager: creates one Langfuse trace per chat request (root span).
    Yields the span so caller can update output, add scores, and log failures.
    If Langfuse is not configured, yields a no-op dummy.
    """
    client = get_langfuse_client()
    if client is None:
        yield _NoOpSpan()
        return
    meta = metadata or {}
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="chat_request",
            input={"query": input_query[:2000]},  # truncate for storage
            metadata=meta,
        ) as span:
            yield span
    except Exception as e:
        logger.warning("Langfuse trace error: %s", e)
        yield _NoOpSpan()


class _NoOpSpan:
    """No-op span when Langfuse is disabled."""

    def score(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update(self, *args: Any, **kwargs: Any) -> None:
        pass
