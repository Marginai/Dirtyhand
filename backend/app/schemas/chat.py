import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Max user/assistant query length — prevent abuse and token overflow
MAX_QUERY_LENGTH = 8_000
MAX_MESSAGE_LENGTH = 50_000  # assistant responses can be longer


def _sanitize_string(value: str) -> str:
    """Strip, remove null bytes, and collapse excessive whitespace."""
    if not isinstance(value, str):
        return str(value)
    s = value.replace("\x00", "").strip()
    return re.sub(r"\s+", " ", s) if s else ""


class ChatMessage(BaseModel):
    # Allow role for backwards compatibility, but the server must never treat
    # client-provided "system" as real system instructions.
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("content", mode="before")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        """Reject empty after sanitization; sanitize for injection surface."""
        s = _sanitize_string(v)
        if not s:
            raise ValueError("Message content cannot be empty")
        return s

class ChatRequest(BaseModel):
    """Client sends full conversation (stateless server). Limit total size for abuse prevention."""

    messages: list[ChatMessage] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_last_user_message_length(self) -> "ChatRequest":
        """Enforce max query length on the last user message (primary input to RAG/LLM)."""
        for m in reversed(self.messages):
            if m.role == "user" and len(m.content) > MAX_QUERY_LENGTH:
                raise ValueError(
                    f"User message exceeds max length of {MAX_QUERY_LENGTH} characters"
                )
        return self


class ChatResponse(BaseModel):
    message: str
    role: Literal["assistant"] = "assistant"


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)
    source: str | None = Field(default=None, max_length=512)


class IngestResponse(BaseModel):
    chunks_added: int


class ScrapeIngestRequest(BaseModel):
    url: str | None = Field(default=None)
    max_chars: int = Field(default=20000, ge=1000, le=100000)
    source: str | None = Field(default=None, max_length=512)


class ScrapeIngestResponse(BaseModel):
    url: str
    chars_scraped: int
    chunks_added: int
    sample: str


class IngestDbResponse(BaseModel):
    filename: str
    pages_extracted: int
    chars_extracted: int
    chunks_added: int
