"""Structured logging for production observability."""

import logging
import sys
from typing import Any

from app.context import request_id_var
from app.settings import get_settings


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    fmt = (
        "%(asctime)s | %(levelname)s | %(name)s | "
        "request_id=%(request_id)s | %(message)s"
    )

    class RequestIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.request_id = request_id_var.get()
            return True

    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)

    # Reduce noise from third-party loggers in production
    if settings.is_production:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("chromadb").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(request_id: str | None = None) -> dict[str, Any]:
    return {"request_id": request_id or "-"}
