import logging

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Reject overly large request bodies early.

    Notes:
    - Uses Content-Length when present (fast, does not consume the body stream).
    - If Content-Length is missing (chunked transfer), we don't enforce here.
    """

    def __init__(self, app, settings: Settings | None = None):
        super().__init__(app)
        self._settings = settings or get_settings()

    def _limit_for_path(self, path: str) -> int | None:
        if path == "/api/v1/chat":
            return self._settings.max_request_bytes_chat
        if path == "/api/v1/ingest":
            return self._settings.max_request_bytes_ingest
        if path == "/api/v1/scrape-ingest":
            return self._settings.max_request_bytes_scrape_ingest
        if path == "/api/v1/ingest-db":
            return self._settings.max_request_bytes_ingest_db
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        limit = self._limit_for_path(request.url.path)
        if limit is None:
            return await call_next(request)

        content_length = request.headers.get("content-length")
        # Fast path: Content-Length present.
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0

            if size and size > limit:
                # Structured error, no stack trace
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={"code": "request_too_large", "message": "Request payload too large"},
                )
        else:
            # Defensive path: Content-Length missing (e.g. chunked transfer).
            # Reading the full body can be expensive for multipart uploads.
            # To avoid breaking ingest-db, we only do streaming/body buffering
            # for the JSON endpoints where it is safe.
            if request.url.path != "/api/v1/ingest-db":
                body = await request.body()  # Starlette caches body for downstream.
                if body is not None and len(body) > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={"code": "request_too_large", "message": "Request payload too large"},
                    )

        return await call_next(request)

