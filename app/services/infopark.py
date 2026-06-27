import re
import logging
from urllib.parse import urljoin, urlencode

import httpx

from app.config import settings
from app.utils.http import fetch_soup, split_emails

logger = logging.getLogger(__name__)


# ── Boilerplate stripping ────────────────────────────────────────────────────
# Infopark's site repeats the full header nav + footer on every page. The
# fallback description extractor (soup.find("main"/"article"/...)) sometimes
# has no clean match and ends up grabbing the whole page body, including this
# boilerplate. We strip it out in two ways:
#   1. Remove known nav/footer DOM elements before extracting text at all.
#   2. As a safety net, regex-strip the known repeating header/footer block
#      from whatever description text we end up with, in case it slipped
#      through some other path.

# Marks the start of the header nav block that always repeats verbatim.
_HEADER_START_RE = re.compile(r"^\s*Home\s*\n?\s*About\b", re.I)

# Marks the start of the footer block ("About Infopark" sidebar heading is
# distinct from the in-body "About Infopark" link, so we anchor on the longer
# repeating sequence that only appears in the footer).
_FOOTER_START_RE = re.compile(
    r"About Infopark\s*\n\s*Overview\s*\n\s*Governing Body\s*\n\s*Executive Council",
    re.I,
)

# Individual nav/footer lines, used to filter line-by-line as a last resort.
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
    """Remove the repeating Infopark header-nav and footer block from text."""
    if not raw:
        return raw

    text = raw

    # Cut everything from the footer marker onward (footer always trails the
    # real content).
    footer_match = _FOOTER_START_RE.search(text)
    if footer_match:
        text = text[: footer_match.start()]

    # Cut a leading header-nav block if present at the very start.
    if _HEADER_START_RE.match(text):
        # Header nav ends right before the company name / "Job Description"
        # heading. Find the first occurrence of a phone number, email, or the
        # literal "Job Description" heading, and cut everything before it.
        cut_markers = list(re.finditer(
            r"(Job Description\b|[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s\-]{8,}\d)",
            text,
        ))
        if cut_markers:
            text = text[cut_markers[0].start():]

    # Line-level cleanup: some short generic words (e.g. "Benefits",
    # "Contact", "Resources") appear BOTH as nav items and as legitimate
    # section headers inside real job descriptions ("Your benefits" section,
    # "Contact us" sign-off). To avoid false positives, we only drop a run of
    # boilerplate lines when several of them appear *consecutively* — i.e. it
    # looks like an actual nav list, not an isolated heading in real content.
    lines = text.split("\n")
    is_boiler = [ln.strip().lower().rstrip(":") in _BOILERPLATE_LINES for ln in lines]

    cleaned = []
    i = 0
    n = len(lines)
    MIN_RUN = 3  # require at least 3 consecutive boilerplate-looking lines
    while i < n:
        if is_boiler[i]:
            j = i
            while j < n and is_boiler[j]:
                j += 1
            run_len = j - i
            if run_len >= MIN_RUN:
                i = j  # skip the whole run — it's a real nav block
                continue
            else:
                cleaned.extend(lines[i:j])  # keep short runs — likely real content
                i = j
                continue
        cleaned.append(lines[i])
        i += 1
    text = "\n".join(cleaned)

    # Collapse excess blank lines left behind by removed boilerplate.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


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

    # Work on a copy of the tree with nav/footer elements removed up front,
    # so neither the description extraction nor the plain-text fallback can
    # accidentally pick up boilerplate.
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

    # Final safety net: strip any nav/footer text that still made it through,
    # regardless of which extraction path produced `description`.
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
