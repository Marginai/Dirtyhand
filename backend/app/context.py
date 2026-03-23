"""Request-scoped context for logging (async-safe)."""

import contextvars

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)


def set_request_id(rid: str) -> contextvars.Token[str]:
    return request_id_var.set(rid)


def reset_request_id(token: contextvars.Token[str]) -> None:
    request_id_var.reset(token)
