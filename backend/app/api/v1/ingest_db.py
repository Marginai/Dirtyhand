import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import Field

from app.api.deps import get_app_settings, get_rag, optional_service_auth
from app.exceptions import RAGError
from app.schemas.chat import IngestDbResponse
from app.services.pdf_service import PDFService
from app.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest-db", tags=["ingest"])


@router.post("", dependencies=[Depends(optional_service_auth)], response_model=IngestDbResponse)
async def ingest_db(
    request: Request,
    file: UploadFile = File(...),
    source: str | None = Form(default=None, max_length=512),
    max_pages: int = Form(default=0, ge=0, le=2000),
    settings: Settings = Depends(get_app_settings),
    rag=Depends(get_rag),
):
    _ = request
    _ = settings

    filename = file.filename or "uploaded.pdf"
    src_label = source or filename

    if not (filename.lower().endswith(".pdf")):
        # We accept content-type mismatch but still require PDF extension for safety.
        # (If you want, we can also validate mime-type.)
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .pdf files are supported")

    data = await file.read()
    if not data:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty PDF upload")

    pdf_service = PDFService()

    # Phase 1 error hardening:
    # Ensure *all* PDF parsing and chunking failures return a clean, structured
    # API error (no generic 500).
    try:
        # Extract text from PDF.
        # If PDF parsing fails (corrupt/invalid), return a clean 4xx error instead
        # of a generic 500 (prevents "Internal Server Error" in the UI).
        try:
            pages_text = await asyncio.to_thread(
                pdf_service.extract_text_pages, data, max_pages=max_pages
            )
        except Exception as e:
            logger.exception("PDF extraction failed")
            from fastapi import HTTPException, status

            client_message = (
                "Invalid or unreadable PDF."
                if settings.is_production and not settings.debug
                else str(e)[:300]
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "pdf_extract_error", "message": client_message},
            ) from e

        chars_extracted = sum(len(t or "") for t in pages_text)

        # Chunk PDF text into documents for RAG.
        try:
            docs = pdf_service.chunk_pages(pages_text, source=src_label)
        except Exception as e:
            logger.exception("PDF chunking failed")
            from fastapi import HTTPException, status

            client_message = (
                "Failed to process PDF content."
                if settings.is_production and not settings.debug
                else str(e)[:300]
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "pdf_chunk_error", "message": client_message},
            ) from e
    except Exception:
        # Let already-raised HTTPExceptions bubble up.
        raise

    # Chunk and ingest
    try:
        chunks_added = rag.add_documents(docs)
    except RAGError as e:
        logger.exception("PDF ingest failed")
        client_message = (
            "PDF ingest failed."
            if settings.is_production and not settings.debug
            else str(e)
        )
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "rag_error", "message": client_message},
        ) from e

    return IngestDbResponse(
        filename=filename,
        pages_extracted=len(pages_text),
        chars_extracted=chars_extracted,
        chunks_added=chunks_added,
    )

