import { Chat } from "./components/Chat";
import { ScrapeIngest } from "./components/ScrapeIngest";

export default function App() {
  return (
    <main style={{ maxWidth: 980, margin: "0 auto", padding: "2rem 1rem" }}>
      <header style={{ marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Agentic RAG Chat</h1>
        <p style={{ margin: "0.35rem 0 0", color: "#64748b", fontSize: "0.9rem" }}>
          Playwright tools + RAG context. Production UI talks to <code>/api/v1/chat</code>.
        </p>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "1rem" }}>
        <Chat />
        <ScrapeIngest />
      </div>
    </main>
  );
}
