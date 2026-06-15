from typing import Optional
from pydantic import BaseModel


class TechnoparkJob(BaseModel):
    job_id: str
    title: str
    company: Optional[str] = None
    company_url: Optional[str] = None
    detail_url: str
    closing_date: Optional[str] = None
    published_date: Optional[str] = None
    contact_email: Optional[str] = None
    career_email: Optional[str] = None
    description: Optional[str] = None
    preferred_skills: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None


class TechnoparkResponse(BaseModel):
    source: str = "technopark.in"
    search_term: str
    total_matched: int
    jobs: list[TechnoparkJob]
