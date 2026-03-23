from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_app_settings
from app.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness — process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
):
    """Readiness — dependencies available."""
    checks: dict[str, str] = {}
    ok = True

    if not settings.openai_api_key:
        checks["openai"] = "missing OPENAI_API_KEY"
        ok = False
    else:
        checks["openai"] = "ok"

    browser = getattr(request.app.state, "browser", None)
    if browser and getattr(browser, "_started", False):
        checks["playwright"] = "ok"
    else:
        checks["playwright"] = "not_started"
        ok = False

    rag = getattr(request.app.state, "rag", None)
    if rag:
        checks["rag"] = "ok"
    else:
        checks["rag"] = "missing"
        ok = False

    status_code = 200 if ok else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={"ready": ok, "checks": checks},
    )
