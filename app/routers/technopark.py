import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_http_client
from app.schemas.technopark import TechnoparkJob, TechnoparkResponse
from app.services import technopark as technopark_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/technopark", tags=["Technopark"])


@router.get(
    "/jobs",
    response_model=TechnoparkResponse,
    summary="Search jobs on Technopark (Trivandrum)",
)
async def search_jobs(
    search: str = Query(..., description="Search keyword — e.g. 'python', 'java', 'react'"),
    max_jobs: int = Query(10, ge=1, le=50, description="Max detail pages to fetch (1-50)"),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> TechnoparkResponse:
    """
    Fetches all matching jobs from **technopark.in/job-crawl** (server-rendered,
    no JS required), filters by keyword, then concurrently scrapes each detail page.
    """
    try:
        stubs = await technopark_service.get_matching_links(search, client)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Technopark listing error: {exc}")

    if not stubs:
        return TechnoparkResponse(search_term=search, total_matched=0, jobs=[])

    tasks = [technopark_service.fetch_detail(stub, client) for stub in stubs[:max_jobs]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs: list[TechnoparkJob] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Technopark detail error: %s", result)
            continue
        jobs.append(TechnoparkJob(**result))

    return TechnoparkResponse(search_term=search, total_matched=len(stubs), jobs=jobs)
