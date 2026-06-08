"""
Job Scraper API — Technopark & Infopark
Run: uvicorn main:app --reload
Docs: http://localhost:8000/docs
"""

import re
import asyncio
import logging
from typing import Optional
from urllib.parse import urlencode, urljoin, quote

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Kerala IT Park Job Scraper",
    description="Scrapes job listings from Technopark (Trivandrum) and Infopark (Kochi)",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Constants ────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

TECHNOPARK_BASE = "https://technopark.in"
INFOPARK_BASE   = "https://infopark.in"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
CAREER_KEYWORDS = ("career", "hr", "recruit", "jobs", "hiring", "talent", "people")


# ── Pydantic Models ──────────────────────────────────────────────────────────
class TechnoparkJob(BaseModel):
    job_id: str
    title: str
    company: Optional[str]
    company_url: Optional[str]
    detail_url: str
    closing_date: Optional[str]
    published_date: Optional[str]
    contact_email: Optional[str]
    career_email: Optional[str]
    description: Optional[str]
    preferred_skills: Optional[str]
    location: Optional[str]
    website: Optional[str]


class InfoparkJob(BaseModel):
    job_id: str
    company_id: str
    title: str
    company: str
    date_of_posting: Optional[str]
    last_date_to_apply: Optional[str]
    detail_url: str
    contact_phone: Optional[str]
    contact_email: Optional[str]
    career_email: Optional[str]
    description: Optional[str]
    location: Optional[str]


class TechnoparkResponse(BaseModel):
    source: str = "technopark.in"
    search_term: str
    total_matched: int
    jobs: list[TechnoparkJob]


class InfoparkResponse(BaseModel):
    source: str = "infopark.in"
    search_term: str
    total_matched: int
    jobs: list[InfoparkJob]


# ── HTTP Helper ───────────────────────────────────────────────────────────────
async def fetch_soup(url: str, client: httpx.AsyncClient) -> BeautifulSoup:
    logger.info(f"Fetching: {url}")
    r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def split_emails(raw_text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (contact_email, career_email) from a block of text."""
    emails = list(dict.fromkeys(EMAIL_RE.findall(raw_text)))  # preserve order, dedupe
    contact, career = None, None
    for e in emails:
        if any(k in e.lower() for k in CAREER_KEYWORDS):
            if career is None:
                career = e
        else:
            if contact is None:
                contact = e
    # If only career-style addresses found, also use one as contact
    if contact is None and career:
        contact = career
    # If only generic addresses found, use first as career too
    if career is None and contact:
        career = contact
    return contact, career


# ══════════════════════════════════════════════════════════════════════════════
# TECHNOPARK SCRAPER
# Strategy:
#   1. Fetch /job-crawl  — a plain HTML page with ALL job links (no JS needed)
#   2. Filter links by search keyword (title match, case-insensitive)
#   3. Fetch each matching /job-details/<id> page concurrently
# ══════════════════════════════════════════════════════════════════════════════
async def tp_get_matching_links(search: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Scrape /job-crawl which is a server-rendered page listing every active job
    as plain <a> tags. Filter by search keyword.
    """
    soup = await fetch_soup(f"{TECHNOPARK_BASE}/job-crawl", client)
    keyword = search.lower()
    jobs = []
    for a in soup.find_all("a", href=re.compile(r"/job-details/\d+")):
        title = a.get_text(strip=True)
        if keyword in title.lower():
            href = a["href"]
            m = re.search(r"/job-details/(\d+)", href)
            if m:
                jobs.append({
                    "job_id": m.group(1),
                    "title": title,
                    "detail_path": href,
                })
    # Deduplicate by job_id (same job may appear twice in the crawl page)
    seen, unique = set(), []
    for j in jobs:
        if j["job_id"] not in seen:
            seen.add(j["job_id"])
            unique.append(j)
    return unique


async def tp_fetch_detail(stub: dict, client: httpx.AsyncClient) -> dict:
    """Fetch a Technopark job detail page and extract all fields."""
    url = urljoin(TECHNOPARK_BASE, stub["detail_path"])
    soup = await fetch_soup(url, client)
    text = soup.get_text(separator=" ", strip=True)

    # ── Title ──────────────────────────────────────────────────────────────
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else stub["title"]

    # ── Company ────────────────────────────────────────────────────────────
    company, company_url = None, None
    c_link = soup.find("a", href=re.compile(r"/company-details/\d+"))
    if c_link:
        company     = c_link.get_text(strip=True)
        company_url = urljoin(TECHNOPARK_BASE, c_link["href"])

    # ── Location ───────────────────────────────────────────────────────────
    location = None
    loc_m = re.search(
        r"(Module|Building|Floor|Plot|Block)[^<\n]{5,150}",
        soup.get_text(separator="\n"),
    )
    if loc_m:
        location = loc_m.group(0).strip()

    # ── Website (first external link) ─────────────────────────────────────
    website = None
    for a in soup.find_all("a", href=re.compile(r"^https?://")):
        h = a["href"]
        if not any(d in h for d in ("technopark.in", "kerala.gov", "apple.com",
                                     "play.google", "twitter", "facebook",
                                     "youtube", "instagram", "linkedin")):
            website = h
            break

    # ── Dates ──────────────────────────────────────────────────────────────
    closing_date, published_date = None, None
    for tag in soup.find_all(string=re.compile(r"Closing\s*Date", re.I)):
        closing_date = re.sub(r"Closing\s*Date\s*[:\-]?\s*", "", str(tag)).strip() or None
    for tag in soup.find_all(string=re.compile(r"Job\s*Published|Published", re.I)):
        published_date = re.sub(r"(Job\s*Published|Published)\s*[:\-]?\s*", "", str(tag)).strip() or None

    # ── Emails ─────────────────────────────────────────────────────────────
    contact_email, career_email = split_emails(text)

    # ── Description ────────────────────────────────────────────────────────
    description, preferred_skills = None, None

    brief_tag = soup.find(string=re.compile(r"Brief\s*Description", re.I))
    if brief_tag:
        parent = brief_tag.find_parent()
        if parent:
            nxt = parent.find_next_sibling()
            description = nxt.get_text(separator="\n", strip=True) if nxt else parent.get_text(strip=True)

    pref_tag = soup.find(string=re.compile(r"Preferred\s*Skills", re.I))
    if pref_tag:
        parent = pref_tag.find_parent()
        if parent:
            nxt = parent.find_next_sibling()
            preferred_skills = nxt.get_text(separator="\n", strip=True) if nxt else None

    if not description:
        # Fallback: all <p> blocks
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        description = "\n\n".join(paras) or None

    return {
        "job_id":          stub["job_id"],
        "title":           title,
        "company":         company,
        "company_url":     company_url,
        "detail_url":      url,
        "closing_date":    closing_date,
        "published_date":  published_date,
        "contact_email":   contact_email,
        "career_email":    career_email,
        "description":     description,
        "preferred_skills":preferred_skills,
        "location":        location,
        "website":         website,
    }


# ══════════════════════════════════════════════════════════════════════════════
# INFOPARK SCRAPER
# ══════════════════════════════════════════════════════════════════════════════
async def ip_get_listing(search: str, client: httpx.AsyncClient) -> list[dict]:
    url = f"{INFOPARK_BASE}/companies/job-search?{urlencode({'search': search})}"
    soup = await fetch_soup(url, client)
    jobs = []
    for row in soup.find_all("tr"):
        link = row.find("a", href=re.compile(r"/company-jobs/details/\d+/\d+"))
        if not link:
            continue
        m = re.search(r"/company-jobs/details/(\d+)/(\d+)", link["href"])
        if not m:
            continue
        cells = row.find_all("td")
        jobs.append({
            "job_id":            m.group(1),
            "company_id":        m.group(2),
            "title":             cells[1].get_text(strip=True) if len(cells) > 1 else link.get_text(strip=True),
            "company":           cells[2].get_text(strip=True) if len(cells) > 2 else "",
            "date_of_posting":   cells[0].get_text(strip=True) if len(cells) > 0 else None,
            "last_date_to_apply":cells[3].get_text(strip=True) if len(cells) > 3 else None,
            "detail_path":       link["href"],
        })
    return jobs


async def ip_fetch_detail(job: dict, client: httpx.AsyncClient) -> dict:
    url = urljoin(INFOPARK_BASE, job["detail_path"])
    soup = await fetch_soup(url, client)
    text = soup.get_text(separator=" ", strip=True)

    # ── Phone ──────────────────────────────────────────────────────────────
    contact_phone = None
    ph = re.search(r"\b(\d{4}[\s/-]\d{7,8}|\+91[\s-]?\d{10}|\d{10})\b", text)
    if ph:
        contact_phone = ph.group(0)

    # ── Emails ─────────────────────────────────────────────────────────────
    contact_email, career_email = split_emails(text)

    # ── Location ───────────────────────────────────────────────────────────
    location = None
    loc_m = re.search(
        r"(Carnival|Infopark|Phase\s*\d|Kakkanad|Kochi|Ernakulam|Thrissur|Cherthala)[^\n<]{5,150}",
        text,
    )
    if loc_m:
        location = loc_m.group(0).strip()

    # ── Description ────────────────────────────────────────────────────────
    description = None
    jd_tag = soup.find(string=re.compile(r"JOB\s*DESCRIPTION", re.I))
    if jd_tag:
        parent = jd_tag.find_parent()
        if parent:
            chunks = [
                sib.get_text(separator="\n", strip=True)
                for sib in parent.next_siblings
                if hasattr(sib, "get_text")
            ]
            description = "\n\n".join(c for c in chunks if c) or None

    if not description:
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"content|body|detail", re.I))
        )
        if main:
            description = main.get_text(separator="\n", strip=True) or None

    return {
        "job_id":             job["job_id"],
        "company_id":         job["company_id"],
        "title":              job["title"],
        "company":            job["company"],
        "date_of_posting":    job.get("date_of_posting"),
        "last_date_to_apply": job.get("last_date_to_apply"),
        "detail_url":         url,
        "contact_phone":      contact_phone,
        "contact_email":      contact_email,
        "career_email":       career_email,
        "description":        description,
        "location":           location,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════
@app.get(
    "/technopark/jobs",
    response_model=TechnoparkResponse,
    summary="Search jobs on Technopark (Trivandrum)",
    tags=["Technopark"],
)
async def technopark_jobs(
    search: str = Query(..., description="Search keyword — e.g. 'python', 'java', 'react'"),
    max_jobs: int = Query(10, ge=1, le=50, description="Max detail pages to fetch (1-50)"),
):
    """
    Fetches all matching jobs from **technopark.in/job-crawl** (server-rendered,
    no JS required), filters by keyword, then concurrently scrapes each detail page.

    Returns job ID, title, company, emails, description, dates, location.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            stubs = await tp_get_matching_links(search, client)
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Technopark listing error: {e}")

        if not stubs:
            return TechnoparkResponse(search_term=search, total_matched=0, jobs=[])

        tasks = [tp_fetch_detail(s, client) for s in stubs[:max_jobs]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs_out = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Technopark detail error: {r}")
            continue
        jobs_out.append(TechnoparkJob(**r))

    return TechnoparkResponse(
        search_term=search,
        total_matched=len(stubs),
        jobs=jobs_out,
    )


@app.get(
    "/infopark/jobs",
    response_model=InfoparkResponse,
    summary="Search jobs on Infopark (Kochi)",
    tags=["Infopark"],
)
async def infopark_jobs(
    search: str = Query(..., description="Search keyword — e.g. 'ai', 'python', 'data science'"),
    max_jobs: int = Query(10, ge=1, le=50, description="Max detail pages to fetch (1-50)"),
):
    """
    Searches **infopark.in/companies/job-search** by keyword, then concurrently
    scrapes each detail page.

    Returns job ID, company ID, title, emails, phone, description, dates, location.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            listing = await ip_get_listing(search, client)
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Infopark listing error: {e}")

        if not listing:
            return InfoparkResponse(search_term=search, total_matched=0, jobs=[])

        tasks = [ip_fetch_detail(j, client) for j in listing[:max_jobs]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs_out = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Infopark detail error: {r}")
            continue
        jobs_out.append(InfoparkJob(**r))

    return InfoparkResponse(
        search_term=search,
        total_matched=len(listing),
        jobs=jobs_out,
    )


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.1.0", "endpoints": ["/technopark/jobs", "/infopark/jobs"]}