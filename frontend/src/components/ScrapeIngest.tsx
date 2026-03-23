import { useCallback, useState } from "react";
import { postChat, postScrapeIngest, type ChatMessage, type ScrapeIngestResponse } from "../api/client";
import { getClientMaxChars, sanitizeClientText } from "../security/client_guardrails";

function formatResponse(r: ScrapeIngestResponse) {
  return [
    `URL: ${r.url}`,
    `Chars scraped: ${r.chars_scraped}`,
    `Chunks added: ${r.chunks_added}`,
    "",
    "Sample:",
    r.sample,
  ].join("\n");
}

export function ScrapeIngest() {
  const [url, setUrl] = useState("");
  const [maxChars, setMaxChars] = useState<number>(20000);
  const [source, setSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScrapeIngestResponse | null>(null);
  const MAX_CHARS = getClientMaxChars();

  // Step 9: optionally ask a question right after ingesting (RAG retrieval should use the new content).
  const [askQuestion, setAskQuestion] = useState<string>("");
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [askError, setAskError] = useState<string | null>(null);

  const onIngestAndAsk = useCallback(async () => {
    const trimmed = url.trim();
    const q = sanitizeClientText(askQuestion);
    if (!q || loading) return;

    setError(null);
    setAskError(null);
    setAskAnswer(null);
    setResult(null);
    setLoading(true);
    try {
      const resp = await postScrapeIngest({
        url: trimmed ? trimmed : null,
        max_chars: maxChars,
        source: source.trim() ? source.trim() : null,
      });
      setResult(resp);

      const prompt = `Using the content you ingested from ${resp.url}, answer the following question:\n${q}`;
      const messages: ChatMessage[] = [{ role: "user", content: prompt }];
      const reply = await postChat(messages);
      setAskAnswer(reply);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Request failed";
      // If ingest fails, show as ingest error; otherwise show as ask error.
      if (!result) {
        setError(msg);
      } else {
        setAskError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [url, askQuestion, maxChars, source, loading, result]);

  const onSubmit = useCallback(async () => {
    const trimmed = url.trim();
    if (loading) return;
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const resp = await postScrapeIngest({
        url: trimmed ? trimmed : null,
        max_chars: maxChars,
        source: source.trim() ? source.trim() : null,
      });
      setResult(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, [url, maxChars, source, loading]);

  return (
    <div
      style={{
        border: "1px solid #e2e8f0",
        borderRadius: 12,
        padding: "1rem",
        background: "#fff",
      }}
    >
      <h2 style={{ margin: "0 0 0.5rem 0", fontSize: "1.05rem" }}>Scrape &amp; Ingest</h2>
      <p style={{ margin: "0 0 1rem 0", color: "#64748b", fontSize: "0.9rem" }}>
        Uses Playwright to scrape the page and stores chunks into Chroma (RAG).
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: "0.85rem", color: "#0f172a", opacity: 0.85 }}>URL</span>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            style={{
              padding: "0.55rem 0.65rem",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              fontFamily: "inherit",
            }}
            disabled={loading}
          />
        </label>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180 }}>
            <span style={{ fontSize: "0.85rem", color: "#0f172a", opacity: 0.85 }}>Max chars</span>
            <input
              type="number"
              value={maxChars}
              min={1000}
              max={100000}
              onChange={(e) => setMaxChars(Number(e.target.value))}
              style={{
                padding: "0.55rem 0.65rem",
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                fontFamily: "inherit",
              }}
              disabled={loading}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 220 }}>
            <span style={{ fontSize: "0.85rem", color: "#0f172a", opacity: 0.85 }}>Source label (optional)</span>
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="e.g. marginai.co.uk"
              style={{
                padding: "0.55rem 0.65rem",
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                fontFamily: "inherit",
              }}
              disabled={loading}
            />
          </label>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <button
            type="button"
            onClick={() => void onSubmit()}
            disabled={loading}
            style={{
              padding: "0.55rem 1rem",
              borderRadius: 8,
              border: "none",
              background: "#0f172a",
              color: "#fff",
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? "Working…" : "Scrape &amp; Ingest"}
          </button>

          <button
            type="button"
            onClick={() => void onIngestAndAsk()}
            disabled={loading || !sanitizeClientText(askQuestion)}
            style={{
              padding: "0.55rem 1rem",
              borderRadius: 8,
              border: "none",
              background: "#0f172a",
              color: "#fff",
              cursor: loading ? "wait" : "pointer",
              opacity: loading || !askQuestion.trim() ? 0.6 : 1,
            }}
            title="Scrape + ingest, then immediately call /api/v1/chat with your question."
          >
            {loading ? "Working…" : "Ingest &amp; Answer"}
          </button>

          {error && (
            <div style={{ color: "#b91c1c", fontSize: "0.9rem" }} role="alert">
              {error}
            </div>
          )}
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: "0.85rem", color: "#0f172a", opacity: 0.85 }}>Question to ask after ingest (Step 9)</span>
          <input
            value={askQuestion}
            onChange={(e) => setAskQuestion(e.target.value)}
            placeholder="e.g. What does the company do?"
            maxLength={MAX_CHARS}
            style={{
              padding: "0.55rem 0.65rem",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              fontFamily: "inherit",
            }}
            disabled={loading}
          />
        </label>

        {result && (
          <div
            style={{
              border: "1px solid #e2e8f0",
              borderRadius: 10,
              padding: "0.75rem",
              background: "#f8fafc",
            }}
          >
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "inherit" }}>
              {formatResponse(result)}
            </pre>
          </div>
        )}

        {askError && (
          <div style={{ color: "#b91c1c", fontSize: "0.9rem" }} role="alert">
            {askError}
          </div>
        )}

        {askAnswer && (
          <div
            style={{
              border: "1px solid #e2e8f0",
              borderRadius: 10,
              padding: "0.75rem",
              background: "#f1f5f9",
            }}
          >
            <strong style={{ display: "block", marginBottom: "0.5rem" }}>Assistant (after ingest)</strong>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "inherit" }}>
              {askAnswer}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

