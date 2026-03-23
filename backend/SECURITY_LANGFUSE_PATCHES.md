# Security Hardening + Langfuse Integration — Summary

This document summarizes all additions and where they were inserted.

---

## 🔐 PART 1 — SECURITY HARDENING

### 1.1 Input Validation

**Location:** `app/schemas/chat.py`

- **MAX_QUERY_LENGTH** (8000 chars): Enforced on the last user message via `@model_validator`
- **Sanitization:** `@field_validator` on `ChatMessage.content`:
  - Strips whitespace
  - Removes null bytes (`\x00`)
  - Collapses excessive whitespace
  - Rejects empty content after sanitization
- **Reject empty:** `min_length=1` on messages and content

### 1.2 Prompt Injection Protection

**New module:** `app/security/prompt_injection.py`

- **Patterns detected:** e.g. "ignore previous instructions", "system prompt", "reveal hidden", "jailbreak", etc.
- **`check_prompt_injection(text) -> (bool, str|None)`:** Returns `(False, pattern)` if malicious
- **`block_if_injection(text)`:** Raises `AppError` (400) and logs the event

**Insertion:** Called in `app/api/v1/chat.py` before `agent.ainvoke()`.

### 1.3 Output Safety

**New module:** `app/security/output_safety.py`

- **`filter_sensitive_output(text)`:** Redacts API keys (`sk-...`), system-prompt leaks before returning
- **Insertion:** Applied to the assistant response in `chat.py` before `ChatResponse(message=filtered)`

### 1.4 Rate Limiting

**Locations:** `app/settings.py`, `app/main.py`, `.env.example`

- **RATE_LIMIT_CHAT_PER_MINUTE** (default 20): Stricter limit for `/api/v1/chat`
- Other routes remain at `RATE_LIMIT_PER_MINUTE` (default 60)

### 1.5 Error Handling

**Location:** `app/main.py` — `_generic_error_handler`

- Never exposes stack traces
- In production or non-debug: always returns `"An unexpected error occurred."`
- Debug: returns `str(exc)` and `type` only — no traceback

---

## 📊 PART 2 — LANGFUSE + PASS RATE

### 2.1 Langfuse Client

**New module:** `app/observability/langfuse_client.py`

- **`get_langfuse_client()`:** Returns Langfuse client if `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set; else `None`
- **`trace_chat_request(input_query, metadata)`:** Context manager that creates one trace per request
- **No-op when disabled:** Yields `_NoOpSpan` when Langfuse is not configured

**Settings:** `app/settings.py` — `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host`, `langfuse_enabled`

### 2.2 Evaluation Function

**New module:** `app/evaluation.py`

- **`evaluate_answer(answer: str, context: str) -> int`**
  - Returns `1` → correct / relevant / grounded
  - Returns `0` → incorrect / hallucinated / failure phrases
- Heuristics: failure phrases, length checks, overlap with context

### 2.3 Trace Contents

Per request, the trace includes:

- **Input:** `query` (truncated to 2000 chars)
- **Output:** `response` or `error`
- **Metadata:** `request_id`, `latency_ms`, `status`, `empty_retrieval`
- **Score:** `name="pass_rate"`, `value=0` or `1`

### 2.4 Failure Tracking

- **empty_retrieval:** Logged in trace metadata when RAG returns no documents
- **agent_error:** Logged when `AgentExecutionError` is raised (score = 0)
- **exception:** Logged on any other exception (score = 0)

---

## 📁 NEW FILES

| Path | Purpose |
|------|---------|
| `app/security/__init__.py` | Exports security helpers |
| `app/security/prompt_injection.py` | Prompt injection detection and blocking |
| `app/security/output_safety.py` | Output filtering (API keys, system prompts) |
| `app/observability/__init__.py` | Exports Langfuse client |
| `app/observability/langfuse_client.py` | Langfuse tracing wrapper |
| `app/evaluation.py` | Pass-rate evaluation function |

---

## 📦 DEPENDENCIES

Added to `requirements.txt`:

```
langfuse>=2.0.0
```

---

## ⚙️ ENV VARIABLES

Add to `.env` for Langfuse (optional):

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
RATE_LIMIT_CHAT_PER_MINUTE=20
```

---

## 🧪 USAGE

- **Without Langfuse:** App works as before; security and validation still apply
- **With Langfuse:** Set keys → traces appear in Langfuse with `pass_rate` scores
- **Flush on shutdown:** `langfuse.flush()` is called in lifespan shutdown
