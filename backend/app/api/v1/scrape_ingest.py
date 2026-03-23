import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.api.deps import get_app_settings, get_browser, get_rag, optional_service_auth
from app.schemas.chat import ScrapeIngestRequest, ScrapeIngestResponse
from app.services.browser_service import BrowserService
from app.services.rag_service import RAGService
from app.exceptions import ConfigurationError
from app.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape-ingest", tags=["scrape"])


@router.post("", dependencies=[Depends(optional_service_auth)])
async def scrape_ingest(
    request: Request,
    body: ScrapeIngestRequest,
    rag: RAGService = Depends(get_rag),
    browser: BrowserService = Depends(get_browser),
    settings: Settings = Depends(get_app_settings),
):
    _ = request
    # `settings.organization_url` is used when the client does not provide `body.url`.

    # Allow missing scheme by defaulting to https when possible.
    url = (body.url or settings.organization_url).strip()
    if not url:
        raise ConfigurationError(
            "Missing URL: provide `url` in the request or set ORGANIZATION_URL in .env"
        )
    if "://" not in url:
        url = f"https://{url}"

    # Validate URL shape (scheme + host) and return clean 422 for bad inputs.
    try:
        TypeAdapter(HttpUrl).validate_python(url)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e

    scraped_text = await browser.navigate_and_extract_text(url)
    chars_scraped = len(scraped_text)
    ingest_text = scraped_text[: body.max_chars]

    meta = {"source": body.source or url}
    try:
        chunks_added = rag.add_text(ingest_text, metadata=meta)
    except Exception as e:
        logger.exception("Scrape-ingest failed")
        client_message = (
            "Scrape-ingest failed."
            if settings.is_production and not settings.debug
            else str(e)
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "scrape_ingest_error", "message": client_message},
        ) from e

    sample = ingest_text[:2000]
    return ScrapeIngestResponse(
        url=url,
        chars_scraped=chars_scraped,
        chunks_added=chunks_added,
        sample=sample,
    )

