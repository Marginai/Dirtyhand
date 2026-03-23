"""Validated application settings (12-factor / production)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values

# Project root (parent of backend/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Agentic RAG Chatbot API"
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        alias="ENVIRONMENT",
    )
    debug: bool = False
    log_level: str = "INFO"
    # Expose /docs and OpenAPI in production when true (default off)
    show_openapi: bool = Field(default=False, alias="SHOW_OPENAPI")

    # OpenAI (required at runtime for chat; validated on first use in services)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _fallback_if_placeholder(cls, v: str) -> str:
        """
        If the runtime env var contains our development placeholder key, fall back
        to the real key from the project's root `.env`.

        This prevents accidental runs with an invalid key when environment variables
        are inherited from earlier test commands.
        """
        if isinstance(v, str) and v.strip() and v.strip().startswith("sk-test-"):
            vals = dotenv_values(_PROJECT_ROOT / ".env")
            real = (vals.get("OPENAI_API_KEY") or "").strip()
            return real
        return v or ""

    # Models
    llm_model: str = Field(default="gpt-5.4", alias="LLM_MODEL")
    embedding_model: str = Field(default="text-embedding-3-large", alias="EMBEDDING_MODEL")

    # RAG / Chroma (persistent on disk)
    rag_collection_name: str = Field(default="rag_docs_gpt54_emb3l", alias="RAG_COLLECTION_NAME")
    chroma_persist_dir: Path = Field(
        default=_PROJECT_ROOT / "backend" / "data" / "chroma",
        alias="CHROMA_PERSIST_DIR",
    )

    # CORS — comma-separated origins in production
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    # Optional: require `Authorization: Bearer <token>` for /api/v1/* mutating routes
    api_service_key: str = Field(default="", alias="API_SERVICE_KEY")

    # Rate limiting (per IP per minute)
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")
    # Stricter limit for chat to prevent abuse (e.g. 10–20 req/min)
    rate_limit_chat_per_minute: int = Field(default=20, alias="RATE_LIMIT_CHAT_PER_MINUTE")

    # Max request body sizes (defense-in-depth against memory/CPU DoS).
    # Enforced via middleware using Content-Length where available.
    max_request_bytes_chat: int = Field(default=8_000_000, alias="MAX_REQUEST_BYTES_CHAT")
    max_request_bytes_ingest: int = Field(default=8_000_000, alias="MAX_REQUEST_BYTES_INGEST")
    max_request_bytes_scrape_ingest: int = Field(default=5_000_000, alias="MAX_REQUEST_BYTES_SCRAPE_INGEST")
    max_request_bytes_ingest_db: int = Field(default=50_000_000, alias="MAX_REQUEST_BYTES_INGEST_DB")

    # Playwright
    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    playwright_timeout_ms: int = Field(default=30_000, alias="PLAYWRIGHT_TIMEOUT_MS")
    # Per-action timeout for navigation/extraction to reduce hang time.
    playwright_action_timeout_ms: int = Field(default=10_000, alias="PLAYWRIGHT_ACTION_TIMEOUT_MS")
    # Optional comma-separated domain allowlist for Playwright navigation.
    # When enforcement is disabled, this is only used to derive a default allowlist.
    playwright_allowed_domains: str = Field(default="", alias="PLAYWRIGHT_ALLOWED_DOMAINS")
    # If true, block navigation to any host not in the allowlist.
    # Default is false to avoid breaking existing scraping behavior.
    playwright_enforce_domain_allowlist: bool = Field(default=False, alias="PLAYWRIGHT_ENFORCE_DOMAIN_ALLOWLIST")
    # Block navigation to private/loopback IPs and localhost.
    playwright_block_private_ips: bool = Field(default=True, alias="PLAYWRIGHT_BLOCK_PRIVATE_IPS")

    # Agent
    rag_retrieval_k: int = Field(default=4, alias="RAG_RETRIEVAL_K")
    agent_recursion_limit: int = Field(default=25, alias="AGENT_RECURSION_LIMIT")

    # RAG guardrails (Phase 2)
    # When using Chroma relevance scores, filter out low-relevance docs.
    # Default is 0.0 so it preserves current behavior until you tune it.
    rag_min_relevance: float = Field(default=0.0, alias="RAG_MIN_RELEVANCE")
    # Cap the number of retrieved docs injected into the LLM context.
    rag_max_docs_in_context: int = Field(default=8, alias="RAG_MAX_DOCS_IN_CONTEXT")

    # Langfuse (optional) — if set, traces and pass-rate scores are logged
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    # Default organization/site URL for Playwright scraping.
    # If blank, tools/endpoints require an explicit `url` from the request.
    organization_url: str = Field(default="", alias="ORGANIZATION_URL")

    @field_validator("chroma_persist_dir", mode="before")
    @classmethod
    def resolve_chroma_path(cls, v: str | Path) -> Path:
        p = Path(v)
        return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
