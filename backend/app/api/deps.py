import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.services.agent_service import AgentService
from app.services.browser_service import BrowserService
from app.services.rag_service import RAGService
from app.settings import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


def get_rag(request: Request) -> RAGService:
    return request.app.state.rag


def get_browser(request: Request) -> BrowserService:
    return request.app.state.browser


def get_agent(request: Request) -> AgentService:
    return request.app.state.agent


async def optional_service_auth(
    settings: Annotated[Settings, Depends(get_app_settings)],
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """If API_SERVICE_KEY is set, require Bearer token."""
    if not settings.api_service_key:
        return
    expected = f"Bearer {settings.api_service_key}"
    # Constant-time compare to reduce token oracle timing side-channels.
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
