import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_http_client
from app.schemas.infopark import InfoparkJob, InfoparkResponse
from app.services import infopark as infopark_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/infopark", tags=["Infopark"])


@router.get(
    "/jobs",
    response_model=InfoparkResponse,
    summary="Search jobs on Infopark (Kochi)",
)
async def search_jobs(
    search: str = Query(..., description="Search keyword — e.g. 'ai', 'python', 'data science'"),
    max_jobs: int = Query(10, ge=1, le=50, description="Max detail pages to fetch (1-50)"),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> InfoparkResponse:
    """
    Searches **infopark.in/companies/job-search** by keyword, then concurrently
    scrapes each detail page.
    """
    try:
        listing = await infopark_service.get_listing(search, client)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Infopark listing error: {exc}")

    if not listing:
        return InfoparkResponse(search_term=search, total_matched=0, jobs=[])

    tasks = [infopark_service.fetch_detail(job, client) for job in listing[:max_jobs]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs: list[InfoparkJob] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Infopark detail error: %s", result)
            continue
        jobs.append(InfoparkJob(**result))

    return InfoparkResponse(search_term=search, total_matched=len(listing), jobs=jobs)
