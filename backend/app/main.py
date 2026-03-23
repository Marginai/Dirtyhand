"""FastAPI application factory — production wiring."""

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.deps import optional_service_auth
from app.api.v1 import chat as chat_handlers
from app.api.v1.ingest import ingest_text
from app.api.v1.router import api_v1_router
from app.api.v1.scrape_ingest import scrape_ingest as scrape_ingest_handler
from app.api.v1.ingest_db import ingest_db as ingest_db_handler
from app.exceptions import AppError, ConfigurationError
from app.logging_config import get_logger, setup_logging
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.request_size_limit import RequestSizeLimitMiddleware
from app.services.agent_service import AgentService
from app.services.browser_service import BrowserService
from app.services.rag_service import RAGService
from app.settings import Settings, get_settings

logger = get_logger(__name__)

# Playwright requires subprocess support on Windows.
# Some environments can end up with an event loop that raises NotImplementedError
# for asyncio subprocess_exec. Set the Windows Proactor policy early (module import time)
# so it affects the event loop used by Uvicorn.
if sys.platform.startswith("win"):
    try:
        if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass


def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    settings = get_settings()
    payload: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if settings.debug and exc.details:
        payload["details"] = exc.details
    return JSONResponse(status_code=400, content=payload)


def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Request validation failed",
            "errors": exc.errors(),
        },
    )


def _http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Ensure HTTPException keeps its intended status code and detail payload.
    A catch-all `Exception` handler can otherwise cause HTTPException to be
    returned as a generic 500.
    """
    # Keep structured API errors stable. If endpoint provides {"code","message"},
    # return it directly; otherwise preserve FastAPI-style {"detail": ...}.
    rid = getattr(request.state, "request_id", "-")
    code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
    logger.info("HTTPException request_id=%s status=%s code=%s", rid, exc.status_code, code)
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never expose stack traces; log internally, return clean API errors."""
    settings = get_settings()
    rid = getattr(request.state, "request_id", "-")
    logger.exception("Unhandled error request_id=%s", rid)

    # Security hardening: map common PDF parsing exceptions to a clean 4xx.
    # This prevents the UI from showing a generic 500 on invalid/corrupt uploads.
    exc_type = type(exc).__name__
    if exc_type in {"PdfStreamError", "PdfReadError", "PdfError"}:
        return JSONResponse(
            status_code=400,
            content={"code": "pdf_extract_error", "message": "Invalid or unreadable PDF."},
        )

    # Always return sanitized response — never expose tracebacks or internal paths
    if settings.is_production or not settings.debug:
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "An unexpected error occurred."},
        )
    # Debug: expose exception message but NEVER stack trace
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": str(exc), "type": type(exc).__name__},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s env=%s", settings.app_name, settings.environment)

    if not settings.openai_api_key:
        raise ConfigurationError(
            "OPENAI_API_KEY is required. Set it in your .env file.",
        )
    # Require API auth in production for all protected mutating routes.
    if settings.is_production and not settings.api_service_key:
        raise ConfigurationError(
            "API_SERVICE_KEY is required in production.",
        )
    # Require explicit non-local CORS configuration in production.
    if settings.is_production and any(
        origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")
        for origin in settings.cors_origin_list
    ):
        raise ConfigurationError(
            "CORS_ORIGINS must be set to your real website domain(s) in production.",
        )
    # In production, force Playwright to block private IP targets.
    if settings.is_production and not settings.playwright_block_private_ips:
        raise ConfigurationError(
            "PLAYWRIGHT_BLOCK_PRIVATE_IPS must be true in production.",
        )

    browser = BrowserService(settings)
    # Do not start Playwright at app boot. In some Windows runtimes this causes
    # noisy subprocess errors even though the API is otherwise healthy.
    # Browser startup is lazy and happens only when browser tools are invoked.
    logger.info("Playwright startup deferred (lazy init)")
    rag = RAGService(settings)
    agent = AgentService(rag=rag, browser=browser, settings=settings)

    app.state.browser = browser
    app.state.rag = rag
    app.state.agent = agent

    yield

    # Playwright shutdown must never prevent app shutdown.
    try:
        await browser.stop()
    except Exception:
        pass
    # Flush Langfuse events on shutdown
    try:
        from app.observability.langfuse_client import get_langfuse_client
        client = get_langfuse_client()
        if client:
            client.flush()
    except Exception:
        pass
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()

    limiter = Limiter(key_func=get_remote_address)
    rate = f"{settings.rate_limit_per_minute}/minute"
    chat_rate = f"{settings.rate_limit_chat_per_minute}/minute"

    show_docs = (not settings.is_production) or settings.show_openapi

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
        lifespan=lifespan,
    )

    app.state.limiter = limiter

    app.add_middleware(RequestIdMiddleware)
    # Defense-in-depth: limit request body size before parsing/processing.
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(HTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(Exception, _generic_error_handler)

    app.include_router(api_v1_router, prefix="/api/v1")

    app.add_api_route(
        "/api/v1/chat",
        limiter.limit(chat_rate)(chat_handlers.post_chat),
        methods=["POST"],
        tags=["chat"],
        dependencies=[Depends(optional_service_auth)],
        name="post_chat",
    )
    app.add_api_route(
        "/api/v1/ingest",
        limiter.limit(rate)(ingest_text),
        methods=["POST"],
        tags=["ingest"],
        dependencies=[Depends(optional_service_auth)],
        name="post_ingest",
    )
    app.add_api_route(
        "/api/v1/scrape-ingest",
        limiter.limit(rate)(scrape_ingest_handler),
        methods=["POST"],
        tags=["scrape"],
        dependencies=[Depends(optional_service_auth)],
        name="scrape_ingest",
    )

    app.add_api_route(
        "/api/v1/ingest-db",
        limiter.limit(rate)(ingest_db_handler),
        methods=["POST"],
        tags=["ingest"],
        dependencies=[Depends(optional_service_auth)],
        name="ingest_db",
    )

    @app.get("/")
    async def root():
        return {"service": settings.app_name, "version": "1.0.0", "docs": "/docs" if show_docs else None}

    return app


app = create_app()
