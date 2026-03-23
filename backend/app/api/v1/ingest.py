import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_app_settings, get_rag, optional_service_auth
from app.exceptions import RAGError
from app.schemas.chat import IngestRequest, IngestResponse
from app.services.rag_service import RAGService
from app.settings import Settings

logger = logging.getLogger(__name__)


async def ingest_text(
    request: Request,
    body: IngestRequest,
    rag: Annotated[RAGService, Depends(get_rag)],
    settings: Annotated[Settings, Depends(get_app_settings)],
):
    _ = request
    _ = settings
    meta = {}
    if body.source:
        meta["source"] = body.source
    try:
        n = rag.add_text(body.text, metadata=meta)
    except RAGError as e:
        logger.exception("Ingest failed")
        client_message = (
            "Ingest failed."
            if settings.is_production and not settings.debug
            else str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "rag_error", "message": client_message},
        ) from e
    logger.info("Ingested %s chunks", n)
    return IngestResponse(chunks_added=n)
