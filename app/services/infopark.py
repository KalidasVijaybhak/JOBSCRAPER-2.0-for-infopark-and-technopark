import re
import logging
from urllib.parse import urljoin, urlencode

import httpx

from app.config import settings
from app.utils.http import fetch_soup, split_emails

logger = logging.getLogger(__name__)


async def get_listing(search: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch the Infopark job-search page and parse the results table."""
    url = f"{settings.infopark_base}/companies/job-search?{urlencode({'search': search})}"
    soup = await fetch_soup(url, client)
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
    return jobs


async def fetch_detail(job: dict, client: httpx.AsyncClient) -> dict:
    """Fetch an Infopark job detail page and extract all fields."""
    url = urljoin(settings.infopark_base, job["detail_path"])
    soup = await fetch_soup(url, client)
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
