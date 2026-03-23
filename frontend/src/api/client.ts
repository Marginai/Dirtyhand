const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const API_BEARER = import.meta.env.VITE_API_BEARER_TOKEN?.trim() ?? "";

function buildHeaders(contentType = true): Record<string, string> {
  const headers: Record<string, string> = {};
  if (contentType) headers["Content-Type"] = "application/json";
  if (API_BEARER) headers["Authorization"] = `Bearer ${API_BEARER}`;
  return headers;
}

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

type ApiErrorShape = {
  code?: string;
  message?: string;
  detail?: unknown;
};

function getApiErrorMessage(statusText: string, err: ApiErrorShape): string {
  if (typeof err.message === "string" && err.message.trim()) return err.message;
  if (typeof err.detail === "string" && err.detail.trim()) return err.detail;
  if (
    err.detail &&
    typeof err.detail === "object" &&
    "message" in err.detail &&
    typeof (err.detail as { message?: unknown }).message === "string"
  ) {
    return (err.detail as { message: string }).message;
  }
  return statusText || "Request failed";
}

export async function postChat(messages: ChatMessage[]): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as ApiErrorShape;
    throw new Error(getApiErrorMessage(res.statusText, err));
  }
  const data = (await res.json()) as { message: string };
  return data.message;
}

export interface ScrapeIngestResponse {
  url: string;
  chars_scraped: number;
  chunks_added: number;
  sample: string;
}

export async function postScrapeIngest(params: {
  url?: string | null;
  max_chars?: number;
  source?: string | null;
}): Promise<ScrapeIngestResponse> {
  const res = await fetch(`${API_BASE}/api/v1/scrape-ingest`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({
      url: params.url ?? null,
      max_chars: params.max_chars ?? 20000,
      source: params.source ?? null,
    }),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as ApiErrorShape;
    throw new Error(getApiErrorMessage(res.statusText, err));
  }

  return (await res.json()) as ScrapeIngestResponse;
}

export interface IngestDbResponse {
  filename: string;
  pages_extracted: number;
  chars_extracted: number;
  chunks_added: number;
}

export async function postIngestDb(file: File, source?: string | null, maxPages = 0): Promise<IngestDbResponse> {
  const form = new FormData();
  form.append("file", file);
  if (source && source.trim()) form.append("source", source.trim());
  form.append("max_pages", String(maxPages));

  const res = await fetch(`${API_BASE}/api/v1/ingest-db`, {
    method: "POST",
    headers: buildHeaders(false),
    body: form,
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as ApiErrorShape;
    throw new Error(getApiErrorMessage(res.statusText, err));
  }

  return (await res.json()) as IngestDbResponse;
}
