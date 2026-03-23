// Client-side defense-in-depth guardrails.
// These are intentionally deterministic (regex/rules) to avoid introducing latency
// and to avoid relying on LLM behavior.

const MAX_CHARS_DEFAULT = 500;

const MAX_CHARS = Number(import.meta.env.VITE_CHAT_INPUT_MAX_CHARS ?? MAX_CHARS_DEFAULT);

export function getClientMaxChars(): number {
  // Fallback defensively if env var is missing/invalid.
  return Number.isFinite(MAX_CHARS) && MAX_CHARS > 0 ? MAX_CHARS : MAX_CHARS_DEFAULT;
}

// Common injection phrases (case-insensitive).
// We redact rather than block to minimize capability impact/false positives.
const INJECTION_PATTERNS: RegExp[] = [
  /ignore\s+(all\s+)?(previous|prior|above|all)\s+instructions/gi,
  /disregard\s+(all\s+)?(previous|prior|above)/gi,
  /reveal\s+(your|the)\s+(system\s+)?prompt/gi,
  /system\s+prompt/gi,
  /print\s+(your|the)\s+(system\s+)?prompt/gi,
  /output\s+your\s+system\s+message/gi,
  /you\s+are\s+now\s+in\s+.*?\s+mode/gi,
  /\b(?:jailbreak|dane\s+mode)\b/gi,
  /\[\/?INST\]/gi,
  /<\|im_start\|>|<\|im_end\|>/gi,
];

function redactInjectionPhrases(text: string): string {
  let out = text;
  for (const re of INJECTION_PATTERNS) {
    out = out.replace(re, "[REDACTED]");
  }
  return out;
}

export function sanitizeClientText(text: string): string {
  const maxChars = getClientMaxChars();

  // Normalize:
  let t = (text ?? "").replace(/\x00/g, "").trim();
  if (!t) return "";

  // Defense-in-depth:
  t = redactInjectionPhrases(t);

  // Cap length to reduce accidental token blowups.
  if (t.length > maxChars) {
    t = t.slice(0, maxChars);
  }

  return t.trim();
}

