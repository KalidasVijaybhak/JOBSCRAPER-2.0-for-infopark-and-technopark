from typing import Optional
from pydantic import BaseModel


class InfoparkJob(BaseModel):
    job_id: str
    company_id: str
    title: str
    company: str
    date_of_posting: Optional[str] = None
    last_date_to_apply: Optional[str] = None
    detail_url: str
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    career_email: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None


class InfoparkResponse(BaseModel):
    source: str = "infopark.in"
    search_term: str
    total_matched: int
    jobs: list[InfoparkJob]
