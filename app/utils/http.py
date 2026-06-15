import re
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
CAREER_KEYWORDS = ("career", "hr", "recruit", "jobs", "hiring", "talent", "people")


async def fetch_soup(url: str, client: httpx.AsyncClient) -> BeautifulSoup:
    logger.info("Fetching: %s", url)
    response = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def split_emails(raw_text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (contact_email, career_email) from a block of text."""
    emails = list(dict.fromkeys(EMAIL_RE.findall(raw_text)))
    contact, career = None, None
    for email in emails:
        if any(k in email.lower() for k in CAREER_KEYWORDS):
            if career is None:
                career = email
        else:
            if contact is None:
                contact = email
    if contact is None and career:
        contact = career
    if career is None and contact:
        career = contact
    return contact, career
