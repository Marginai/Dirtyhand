import { useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { postChat, type ChatMessage } from "../api/client";
import { getClientMaxChars, sanitizeClientText } from "../security/client_guardrails";

export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const MAX_CHARS = getClientMaxChars();

  const send = useCallback(async () => {
    const text = sanitizeClientText(input);
    if (!text || loading) return;
    setError(null);
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const reply = await postChat(next);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        border: "1px solid #e2e8f0",
        borderRadius: 12,
        padding: "1rem",
        background: "#fff",
        minHeight: 420,
      }}
    >
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        {messages.length === 0 && (
          <p style={{ color: "#94a3b8", margin: 0 }}>Ask a question or request a webpage scrape.</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "90%",
              padding: "0.6rem 0.85rem",
              borderRadius: 10,
              background: m.role === "user" ? "#0ea5e9" : "#f1f5f9",
              color: m.role === "user" ? "#fff" : "#0f172a",
            }}
          >
            <strong style={{ fontSize: "0.7rem", opacity: 0.85 }}>{m.role}</strong>
            <div style={{ marginTop: 6 }}>
              <div className="messageMarkdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
              </div>
            </div>
          </div>
        ))}
      </div>
      {error && (
        <div style={{ color: "#b91c1c", fontSize: "0.875rem" }} role="alert">
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message…"
          rows={2}
          maxLength={MAX_CHARS}
          style={{
            flex: 1,
            resize: "vertical",
            padding: "0.5rem 0.65rem",
            borderRadius: 8,
            border: "1px solid #cbd5e1",
            fontFamily: "inherit",
          }}
          disabled={loading}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={loading || !sanitizeClientText(input)}
          style={{
            alignSelf: "flex-end",
            padding: "0.5rem 1rem",
            borderRadius: 8,
            border: "none",
            background: "#0f172a",
            color: "#fff",
            cursor: loading ? "wait" : "pointer",
            opacity: loading || !input.trim() ? 0.6 : 1,
          }}
        >
          {loading ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
