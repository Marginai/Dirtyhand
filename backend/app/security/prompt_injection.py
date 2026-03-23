"""Prompt injection detection — blocks or logs malicious user input before LLM."""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# Malicious patterns (case-insensitive) — extend as needed
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|all)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"forget\s+(everything|all)\s+(you|above)",
    r"system\s+prompt",
    r"reveal\s+(your|the)\s+(system\s+)?prompt",
    r"show\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
    r"what\s+are\s+your\s+(system\s+)?instructions",
    r"print\s+(your|the)\s+prompt",
    r"output\s+your\s+system\s+message",
    r"developer\s+mode",
    r"jailbreak",
    r"dane\s+mode",  # common jailbreak variant
    r"you\s+are\s+now\s+in\s+.*\s+mode",
    r"\[INST\]|\[/INST\]",  # instruction-tag manipulation
    r"<\|im_start\|>|<\|im_end\|>",  # chat template tokens
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def check_prompt_injection(text: str) -> Tuple[bool, str | None]:
    """
    Check if input contains prompt-injection patterns.

    Returns:
        (is_safe, matched_pattern_or_none)
        - (True, None) if safe
        - (False, pattern) if malicious pattern detected
    """
    if not text or not text.strip():
        return True, None
    normalized = " ".join(text.split())
    for pat in _COMPILED:
        if pat.search(normalized):
            return False, pat.pattern
    return True, None


def block_if_injection(text: str, log_event: bool = True) -> None:
    """
    Raise if prompt injection detected. Call before sending to LLM.
    Logs the event when configured.
    """
    is_safe, matched = check_prompt_injection(text)
    if not is_safe and matched:
        if log_event:
            logger.warning(
                "Prompt injection blocked: pattern=%s snippet=%s",
                matched,
                (text[:200] + "…") if len(text) > 200 else text,
            )
        from app.exceptions import AppError

        raise AppError(
            "Input contains disallowed content.",
            code="prompt_injection_blocked",
            details={"blocked_pattern": matched[:50]},
        )


def _is_high_risk_pattern(pattern_regex: str) -> bool:
    """
    Decide whether a matched injection pattern is high-risk (must block)
    or low-risk (we can redact and continue).

    This keeps capability for benign requests like "what is a system prompt?"
    while still blocking common jailbreak/instruction-stealing payloads.
    """
    high_risk_markers = [
        "ignore\\s+",
        "disregard",
        "reveal\\s+",
        "print\\s+",
        "output\\s+your",
        "jailbreak",
        "dane\\s+mode",
        "<\\\\|im_start\\\\|>",
        "<\\\\|im_end\\\\|>",
        "you\\\\s+are\\\\s+now",
        "forget\\\\s+",
    ]
    return any(marker in pattern_regex for marker in high_risk_markers)


def sanitize_or_block_prompt_injection(text: str, log_event: bool = True) -> str:
    """
    Sanitize injection-ish content deterministically.
    - If a high-risk pattern is detected: raise AppError (blocked).
    - Otherwise: redact common keywords so the LLM doesn't follow them.
    """
    is_safe, matched = check_prompt_injection(text)
    if is_safe:
        return text

    if not matched:
        return text

    if _is_high_risk_pattern(matched):
        # High risk: block the request.
        block_if_injection(text, log_event=log_event)

    # Low risk: redact keywords and continue.
    # Keep it simple and deterministic to minimize latency and false positives.
    redacted = text
    redacted = re.sub(r"system\\s+prompt", "[REDACTED SYSTEM PROMPT]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        r"system\\s+instructions", "[REDACTED SYSTEM INSTRUCTIONS]", redacted, flags=re.IGNORECASE
    )
    redacted = re.sub(r"developer\\s+mode", "[REDACTED DEVELOPER MODE]", redacted, flags=re.IGNORECASE)

    if log_event:
        logger.warning("Prompt injection sanitized: pattern=%s snippet=%s", matched, (text[:200] + "…") if len(text) > 200 else text)
    return redacted
