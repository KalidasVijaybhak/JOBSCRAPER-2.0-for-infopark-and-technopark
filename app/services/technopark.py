import re
import logging
from urllib.parse import urljoin, urlparse, parse_qs, unquote_plus

import httpx

from app.config import settings
from app.utils.http import fetch_soup, split_emails

logger = logging.getLogger(__name__)


async def get_matching_links(search: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Scrape /job-crawl — a server-rendered page listing every active job as plain <a> tags.
    Filters links by the search keyword (case-insensitive title match).
    """
    soup = await fetch_soup(f"{settings.technopark_base}/job-crawl", client)
    keyword = search.lower()
    jobs = []

    for anchor in soup.find_all("a", href=re.compile(r"/job-details/\d+")):
        title = anchor.get_text(strip=True)
        if keyword not in title.lower():
            continue
        match = re.search(r"/job-details/(\d+)", anchor["href"])
        if match:
            jobs.append({
                "job_id": match.group(1),
                "title": title,
                "detail_path": anchor["href"],
            })

    seen: set[str] = set()
    unique = []
    for job in jobs:
        if job["job_id"] not in seen:
            seen.add(job["job_id"])
            unique.append(job)
    return unique


async def fetch_detail(stub: dict, client: httpx.AsyncClient) -> dict:
    """Fetch a Technopark job detail page and extract all fields."""
    url = urljoin(settings.technopark_base, stub["detail_path"])
    soup = await fetch_soup(url, client)
    text = soup.get_text(separator=" ", strip=True)

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else stub["title"]

    # ── Company ──────────────────────────────────────────────────────────────
    # FIX: the page has TWO <a> tags pointing to /company-details/<id> — one
    # wraps the logo <img> (empty text), one wraps the company name text.
    # soup.find() returns whichever appears first in the DOM, which is usually
    # the image link, so `company` ended up "". We now scan ALL matches and
    # take the first one with non-empty text, falling back to decoding the
    # name straight out of the `company=` query parameter (always present),
    # and finally to a nearby heading tag as a last resort.
    company, company_url = None, None
    company_links = soup.find_all("a", href=re.compile(r"/company-details/\d+"))

    for link in company_links:
        href = link["href"]
        if company_url is None:
            company_url = urljoin(settings.technopark_base, href)
        link_text = link.get_text(strip=True)
        if link_text:
            company = link_text
            company_url = urljoin(settings.technopark_base, href)
            break

    if not company and company_links:
        qs = parse_qs(urlparse(company_links[0]["href"]).query)
        if "company" in qs:
            company = unquote_plus(qs["company"][0]).strip()

    if not company:
        for tag in soup.find_all(["h2", "h3"]):
            candidate = tag.get_text(strip=True)
            if candidate and candidate.lower() != title.lower():
                company = candidate
                break

    location = None
    loc_match = re.search(
        r"(Module|Building|Floor|Plot|Block)[^<\n]{5,150}",
        soup.get_text(separator="\n"),
    )
    if loc_match:
        location = loc_match.group(0).strip()

    website = None
    excluded_domains = (
        "technopark.in", "kerala.gov", "apple.com",
        "play.google", "twitter", "facebook", "youtube", "instagram", "linkedin",
    )
    for anchor in soup.find_all("a", href=re.compile(r"^https?://")):
        href = anchor["href"]
        if not any(d in href for d in excluded_domains):
            website = href
            break

    closing_date, published_date = None, None
    for tag in soup.find_all(string=re.compile(r"Closing\s*Date", re.I)):
        closing_date = re.sub(r"Closing\s*Date\s*[:\-]?\s*", "", str(tag)).strip() or None
    for tag in soup.find_all(string=re.compile(r"Job\s*Published|Published", re.I)):
        published_date = re.sub(r"(Job\s*Published|Published)\s*[:\-]?\s*", "", str(tag)).strip() or None

    contact_email, career_email = split_emails(text)

    description, preferred_skills = None, None

    brief_tag = soup.find(string=re.compile(r"Brief\s*Description", re.I))
    if brief_tag:
        parent = brief_tag.find_parent()
        if parent:
            next_sibling = parent.find_next_sibling()
            description = (
                next_sibling.get_text(separator="\n", strip=True)
                if next_sibling
                else parent.get_text(strip=True)
            )

    pref_tag = soup.find(string=re.compile(r"Preferred\s*Skills", re.I))
    if pref_tag:
        parent = pref_tag.find_parent()
        if parent:
            next_sibling = parent.find_next_sibling()
            preferred_skills = next_sibling.get_text(separator="\n", strip=True) if next_sibling else None

    if not description:
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        description = "\n\n".join(paras) or None

    return {
        "job_id": stub["job_id"],
        "title": title,
        "company": company,
        "company_url": company_url,
        "detail_url": url,
        "closing_date": closing_date,
        "published_date": published_date,
        "contact_email": contact_email,
        "career_email": career_email,
        "description": description,
        "preferred_skills": preferred_skills,
        "location": location,
        "website": website,
    }
