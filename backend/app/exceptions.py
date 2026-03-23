"""Application-specific errors."""

from typing import Any


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, code: str = "app_error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ConfigurationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="configuration_error")


class AgentExecutionError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="agent_execution_error", details=details)


class RAGError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="rag_error")
