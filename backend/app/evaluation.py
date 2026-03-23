"""Pass-rate evaluation — simple heuristic or LLM judge for answer quality."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.settings import Settings

logger = logging.getLogger(__name__)

# Phrases that suggest failure / non-answer
FAILURE_PHRASES = [
    r"i\s+could\s+not\s+(produce|find)",
    r"i\s+couldn't\s+find",
    r"i\s+don't\s+have\s+(enough\s+)?information",
    r"i\s+do\s+not\s+have",
    r"no\s+(relevant\s+)?(results?|information|context|documents?)",
    r"i\s+was\s+unable",
    r"cannot\s+answer",
    r"unable\s+to\s+answer",
    r"i\s+don't\s+know",
    r"i\s+am\s+not\s+sure",
    r"insufficient\s+information",
    r"no\s+context",
]

_FAILURE_RE = re.compile("|".join(f"({p})" for p in FAILURE_PHRASES), re.IGNORECASE)


def evaluate_answer(
    answer: str,
    context: str,
    settings: "Settings | None" = None,
) -> int:
    """
    Evaluate if the answer is correct / relevant / grounded.

    Returns:
        1 — correct, relevant, grounded
        0 — incorrect, hallucinated, or generic failure

    Uses a simple heuristic by default. Can be extended to use an LLM judge.
    """
    if not answer or not answer.strip():
        return 0
    answer_lower = answer.strip().lower()
    context_lower = (context or "").strip().lower()

    # Grounding rule (Phase 5):
    # If we have no retrieved context, the answer cannot be grounded in evidence.
    if not context_lower:
        return 0

    # Heuristic 1: Answer contains failure phrases → 0
    if _FAILURE_RE.search(answer_lower):
        return 0

    # Heuristic 2: Non-empty context but answer is very short → likely insufficient
    if context_lower and len(answer.strip()) < 20:
        return 0

    # Heuristic 3: Answer overlaps with context (grounded) → 1
    # Simple overlap: any substantial word from context appears in answer
    if context_lower:
        context_words = set(w for w in re.split(r"\W+", context_lower) if len(w) > 4)
        answer_words = set(w for w in re.split(r"\W+", answer_lower) if len(w) > 4)
        overlap = len(context_words & answer_words) / max(len(context_words), 1)
        if overlap < 0.02 and len(answer_words) > 5:
            # Answer is long but shares almost no vocabulary with context — possible hallucination
            return 0

    # Default: assume pass
    return 1
