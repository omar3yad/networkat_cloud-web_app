"""
Client-portal theme — `GET /api/v2/client/ui/theme.css`.

Public (no auth): fonts and icon colors only, nothing sensitive. Registered in
main.py without `_auth`. Any failure returns the default CSS with 200.
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.services import appearance_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/client/ui", tags=["Client appearance"])


@router.get("/theme.css")
def theme_css(db: Session = Depends(get_db)):
    try:
        appearance_service.ensure_defaults(db)
        values = appearance_service.load_values(db)
    except Exception as exc:
        logger.error("theme.css: %s", exc)
        values = {}
    return Response(
        appearance_service.theme_css(values),
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=60"},
    )
