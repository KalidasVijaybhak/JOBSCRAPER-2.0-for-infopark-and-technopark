import re
import logging
from urllib.parse import urljoin, urlencode

import httpx

from app.config import settings
from app.utils.http import fetch_soup, split_emails

logger = logging.getLogger(__name__)


# ── Boilerplate stripping (unchanged) ────────────────────────────────────────
_HEADER_START_RE = re.compile(r"^\s*Home\s*\n?\s*About\b", re.I)
_FOOTER_START_RE = re.compile(
    r"About Infopark\s*\n\s*Overview\s*\n\s*Governing Body\s*\n\s*Executive Council",
    re.I,
)
_BOILERPLATE_LINES = {
    "home", "about", "overview", "governing body", "executive council",
    "team infopark", "rti act 2005", "rts act 2012", "careers @ park centre",
    "setup your business", "types of space", "how to apply for space",
    "benefits", "client service", "amenities", "shuttle services",
    "company login", "companies@infopark", "company a-z listing",
    "jobs@infopark", "resources", "media kit", "media hub", "downloads",
    "tenders", "infopark newsletter", "contact", "job opportunities",
    "career opportunities", "back", "about infopark", "infrastructure",
    "infopark kochi phase 1", "infopark kochi phase 2", "infopark thrissur",
    "infopark cherthala", "resource", "quick links", "ecosystem",
    "new initiatives", "testimonials", "companies", "job search",
    "contact us", "infoparks kerala,",
}


def _strip_boilerplate(raw: str) -> str:
    if not raw:
        return raw
    text = raw
    footer_match = _FOOTER_START_RE.search(text)
    if footer_match:
        text = text[: footer_match.start()]
    if _HEADER_START_RE.match(text):
        cut_markers = list(re.finditer(
            r"(Job Description\b|[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s\-]{8,}\d)",
            text,
        ))
        if cut_markers:
            text = text[cut_markers[0].start():]
    lines = text.split("\n")
    is_boiler = [ln.strip().lower().rstrip(":") in _BOILERPLATE_LINES for ln in lines]
    cleaned = []
    i, n, MIN_RUN = 0, len(lines), 3
    while i < n:
        if is_boiler[i]:
            j = i
            while j < n and is_boiler[j]:
                j += 1
            if j - i >= MIN_RUN:
                i = j
                continue
            cleaned.extend(lines[i:j])
            i = j
            continue
        cleaned.append(lines[i])
        i += 1
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ── Listing ───────────────────────────────────────────────────────────────────
# /companies/job-search?search=<term> IS the correct, working endpoint — this
# was confirmed by directly testing it: search=ai returns a results page
# containing only AI-related job titles (AI Engineer, Agentic AI Architect,
# etc.), correctly filtered server-side.
#
# HOWEVER, the same endpoint is unreliable for some other terms (observed:
# search=python, search=java, search=react all silently drop the `search`
# param server-side and redirect to the generic unfiltered listing instead of
# raising an error). This looks like a caching/routing bug on Infopark's end
# rather than the endpoint having moved — it is NOT consistent across terms.
#
# To handle this robustly without guessing which terms are "safe": we always
# try the server-side search first (cheap — one request), and only fall back
# to manually paginating + filtering ourselves if we can detect the server
# silently ignored our keyword.

SEARCH_PATH = "/companies/job-search"
LISTING_PATH = "/companies/job-search"  # same path, paginated via ?page=N
MAX_PAGES_TO_SCAN = 30


def _parse_listing_page(soup) -> tuple[list[dict], bool]:
    """Parse one listing page's table rows. Returns (jobs, has_more_pages)."""
    jobs = []
    for row in soup.find_all("tr"):
        link = row.find("a", href=re.compile(r"/company-jobs/details/\d+/\d+"))
        if not link:
            continue
        match = re.search(r"/company-jobs/details/(\d+)/(\d+)", link["href"])
        if not match:
            continue
        cells = row.find_all("td")
        jobs.append({
            "job_id": match.group(1),
            "company_id": match.group(2),
            "title": cells[1].get_text(strip=True) if len(cells) > 1 else link.get_text(strip=True),
            "company": cells[2].get_text(strip=True) if len(cells) > 2 else "",
            "date_of_posting": cells[0].get_text(strip=True) if cells else None,
            "last_date_to_apply": cells[3].get_text(strip=True) if len(cells) > 3 else None,
            "detail_path": link["href"],
        })

    # The pager shows numbered links back to earlier pages even on the LAST
    # page, so "any ?page=N link present" is not a reliable end-of-list
    # signal. We specifically look for an active "›" (next) link instead —
    # on the true last page it renders as plain text with no href.
    has_more = False
    for a in soup.find_all("a", href=re.compile(r"job-search(\?page=\d+)?$")):
        if a.get_text(strip=True) in ("›", "»", "next", "Next"):
            has_more = True
            break
    return jobs, has_more


def _results_look_filtered(jobs: list[dict], keyword: str) -> bool:
    """
    Heuristic check for whether the server actually applied our search filter.
    If at least one job's title or company doesn't contain the keyword, the
    server is very likely returning the generic unfiltered list rather than
    real search results (a true filtered result set should have every row
    matching). Empty result sets are NOT treated as failure — a real search
    can legitimately return zero matches.
    """
    if not jobs:
        return True  # zero results is a valid filtered outcome, not a failure
    keyword = keyword.lower()
    return all(keyword in f"{j['title']} {j['company']}".lower() for j in jobs)


async def _paginate_and_filter(search: str, client: httpx.AsyncClient) -> list[dict]:
    """Fallback: manually walk every listing page and filter client-side."""
    keyword = search.lower().strip()
    matched: list[dict] = []
    seen_job_ids: set[str] = set()

    page = 1
    while page <= MAX_PAGES_TO_SCAN:
        url = (
            f"{settings.infopark_base}{LISTING_PATH}"
            if page == 1
            else f"{settings.infopark_base}{LISTING_PATH}?page={page}"
        )
        try:
            soup = await fetch_soup(url, client)
        except httpx.HTTPStatusError as e:
            logger.warning(f"Infopark fallback listing page {page} failed: {e}")
            break

        jobs, has_more = _parse_listing_page(soup)
        if not jobs:
            break

        for job in jobs:
            if job["job_id"] in seen_job_ids:
                continue
            seen_job_ids.add(job["job_id"])
            haystack = f"{job['title']} {job['company']}".lower()
            if not keyword or keyword in haystack:
                matched.append(job)

        if not has_more:
            break
        page += 1

    return matched


async def get_listing(search: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Search for jobs by keyword. Tries the server-side search endpoint first
    (fast — one request); if the response shows signs the server ignored our
    `search` param (returned the generic unfiltered list instead), falls back
    to paginating the listing ourselves and filtering client-side.
    """
    url = f"{settings.infopark_base}{SEARCH_PATH}?{urlencode({'search': search})}"
    try:
        soup = await fetch_soup(url, client)
    except httpx.HTTPStatusError as e:
        logger.warning(f"Infopark search request failed, falling back to pagination: {e}")
        return await _paginate_and_filter(search, client)

    jobs, _ = _parse_listing_page(soup)

    if _results_look_filtered(jobs, search):
        return jobs

    logger.info(
        f"Infopark server-side search for '{search}' looks unfiltered "
        f"(got generic results) — falling back to manual pagination."
    )
    return await _paginate_and_filter(search, client)


async def fetch_detail(job: dict, client: httpx.AsyncClient) -> dict:
    """Fetch an Infopark job detail page and extract all fields."""
    url = urljoin(settings.infopark_base, job["detail_path"])
    soup = await fetch_soup(url, client)

    for tag in soup.find_all(["nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    contact_phone = None
    phone_match = re.search(r"\b(\d{4}[\s/-]\d{7,8}|\+91[\s-]?\d{10}|\d{10})\b", text)
    if phone_match:
        contact_phone = phone_match.group(0)

    contact_email, career_email = split_emails(text)

    location = None
    loc_match = re.search(
        r"(Carnival|Infopark|Phase\s*\d|Kakkanad|Kochi|Ernakulam|Thrissur|Cherthala)[^\n<]{5,150}",
        text,
    )
    if loc_match:
        location = loc_match.group(0).strip()

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
        main_tag = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"content|body|detail", re.I))
        )
        if main_tag:
            description = main_tag.get_text(separator="\n", strip=True) or None

    description = _strip_boilerplate(description) if description else None

    return {
        "job_id": job["job_id"],
        "company_id": job["company_id"],
        "title": job["title"],
        "company": job["company"],
        "date_of_posting": job.get("date_of_posting"),
        "last_date_to_apply": job.get("last_date_to_apply"),
        "detail_url": url,
        "contact_phone": contact_phone,
        "contact_email": contact_email,
        "career_email": career_email,
        "description": description,
        "location": location,
    }
