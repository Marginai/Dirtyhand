"""Output safety — filter system prompts, API keys, and other sensitive data before returning to client."""

import re

# API key patterns (OpenAI, etc.) — redact before sending to user
API_KEY_PATTERN = re.compile(
    r"(sk-[a-zA-Z0-9]{20,})|"
    r"(sk-proj-[a-zA-Z0-9_-]{20,})|"
    r"(api[_-]?key['\"]?\s*[:=]\s*['\"]?[a-zA-Z0-9_-]{20,})",
    re.IGNORECASE,
)

# Common system-prompt leak phrases — replace with safe placeholder
SYSTEM_LEAK_PATTERNS = [
    (re.compile(r"As an AI (?:assistant|model)[^.]*\.", re.IGNORECASE), "[Response filtered]"),
    (re.compile(r"You are (?:a helpful|an AI) (?:assistant|model)[^.]*\.", re.IGNORECASE), "[Response filtered]"),
    (re.compile(r"\[System\s*:\s*[^\]]{50,}\]", re.IGNORECASE), "[Internal content redacted]"),
    (re.compile(r"<\|(?:system|im_start)\|>[^<]{100,}"), "[Internal content redacted]"),
]

REDACTION_PLACEHOLDER = "[REDACTED]"


def filter_sensitive_output(text: str) -> str:
    """
    Sanitize LLM output before returning to client.
    Prevents leaking system prompts and API keys.
    """
    if not text:
        return text
    out = text
    # Redact API keys
    out = API_KEY_PATTERN.sub(REDACTION_PLACEHOLDER, out)
    for pat, replacement in SYSTEM_LEAK_PATTERNS:
        out = pat.sub(replacement, out)
    return out


def contains_sensitive_output(text: str) -> bool:
    """
    Best-effort deterministic detection of sensitive/superset-leak patterns.
    Used for additional metadata/guardrails (filtering happens via filter_sensitive_output()).
    """
    if not text:
        return False
    if API_KEY_PATTERN.search(text):
        return True
    for pat, _replacement in SYSTEM_LEAK_PATTERNS:
        if pat.search(text):
            return True
    return False
