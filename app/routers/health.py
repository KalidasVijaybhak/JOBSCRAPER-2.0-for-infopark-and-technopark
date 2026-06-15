from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": settings.app_version,
        "endpoints": ["/technopark/jobs", "/infopark/jobs"],
    }
