# Agentic RAG Chatbot (production-oriented)

FastAPI backend with **LangGraph** + **Playwright** tools and **Chroma RAG** (no `MemorySaver` / checkpointer).  
React (TypeScript) UI. Optional Docker Compose stack.

**Architecture (diagram + layers):** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Request Flow (canonical)

```text
[ React UI ]
      ↓
[ FastAPI backend ]
      ↓
[ LangGraph chatbot logic ]
      ↓
[ OpenAI / tools / APIs ]
```

### Implementation mapping

- `React UI` -> `frontend/` (`Chat.tsx`, `ScrapeIngest.tsx`)
- `FastAPI backend` -> `backend/app/main.py`, `backend/app/api/v1/*`
- `LangGraph chatbot logic` -> `backend/app/services/agent_service.py`
- `OpenAI / tools / APIs` -> `backend/app/services/browser_service.py`, `backend/app/services/rag_service.py`, OpenAI models in `agent_service.py`

## Features

- **RAG**: persistent Chroma vector store; context injected per turn from the user’s latest message.
- **Agent tools**: `scrape_text` and `scrape_and_ingest` (Playwright Chromium).
- **API**: versioned routes under `/api/v1`, rate limiting (SlowAPI), optional bearer auth, structured logging + `X-Request-ID`.
- **Ops**: health `/api/v1/health`, readiness `/api/v1/ready`, Dockerfiles, non-root user in backend image.

## Layout

```
backend/app/          # FastAPI application package
frontend/             # Vite + React UI
.env                  # Your secrets (not committed)
docker-compose.yml
```

## Local development

1. **Environment**  
   Copy `.env.example` → `.env` and set `OPENAI_API_KEY`.

2. **Backend** (from repo root):

   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   playwright install chromium
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Frontend**:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Dev server proxies `/api` → `http://127.0.0.1:8000`.  
   For a fixed API URL instead, set `VITE_API_BASE_URL` in `frontend/.env`.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Liveness |
| GET | `/api/v1/ready` | Readiness (OpenAI key, Playwright, RAG) |
| POST | `/api/v1/chat` | JSON `{ "messages": [{ "role","content" }] }` → `{ "message" }` |
| POST | `/api/v1/ingest` | JSON `{ "text", "source?" }` → chunk into RAG |
| POST | `/api/v1/scrape-ingest` | JSON `{ "url?", "max_chars?", "source?" }` → scrape+chunk into RAG |
| POST | `/api/v1/ingest-db` | `multipart/form-data` upload `file` (PDF) + optional `source` → extract+chunk into RAG |

If `API_SERVICE_KEY` is set, send `Authorization: Bearer <API_SERVICE_KEY>` on `POST` routes.

### Default scrape URL
Set `ORGANIZATION_URL` in your root `.env` to the site you want to scrape (e.g. `https://marginai.co.uk`).
When `url` is omitted/blank, both the agent tools and `/api/v1/scrape-ingest` will use `ORGANIZATION_URL`.

## Production

- Set `ENVIRONMENT=production`, tighten `CORS_ORIGINS` to your real origins.
- Run backend with a reverse proxy (TLS, timeouts). Example:

  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
  ```

- Use **one** uvicorn worker per instance if Playwright runs in-process (default here). Scale horizontally with multiple containers and sticky sessions only if you add shared session state later.
- OpenAPI UI is disabled in production unless `SHOW_OPENAPI=true`.

### Docker Compose

```bash
docker compose up --build
```

- UI: http://localhost (nginx → static React, `/api` → backend)  
- API direct: http://localhost:8000  

Ensure `.env` exists with `OPENAI_API_KEY`. Adjust `CORS_ORIGINS` if you use another host/port.

## Switching models (GPT-5.4 + embeddings-3-large)

If you change `LLM_MODEL` / `EMBEDDING_MODEL`, use a new `RAG_COLLECTION_NAME` (recommended), then run **Scrape & Ingest** again to recreate vectors.

## Tests

```bash
cd backend
pip install -r requirements.txt
playwright install chromium
pytest
```

## Security checklist

- Never commit `.env`.
- Set `API_SERVICE_KEY` when exposing the API publicly.
- Restrict `CORS_ORIGINS` in production.
- Put the stack behind HTTPS and rate-limit at the edge (e.g. CDN / API gateway) for heavy traffic.
