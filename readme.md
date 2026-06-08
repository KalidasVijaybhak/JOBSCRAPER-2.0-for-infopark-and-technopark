# Kerala IT Park Job Scraper API

FastAPI application that scrapes job listings with full details from:
- **Technopark** (Trivandrum) — `technopark.in`
- **Infopark** (Kochi) — `infopark.in`

## Features

- Search jobs by keyword via query param
- Extracts job ID, title, company, description
- Extracts **contact email** and **career/HR email**
- Concurrent detail fetching (fast)
- Clean JSON output with Pydantic models
- Interactive Swagger docs at `/docs`

---

## Setup

```bash
# 1. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
uvicorn main:app --reload --port 8000
```

---

## Endpoints

### Technopark Jobs
```
GET /technopark/jobs?search=<keyword>&max_jobs=10
```

**Example:**
```bash
curl "http://localhost:8000/technopark/jobs?search=python&max_jobs=5"
```

**Response:**
```json
{
  "source": "technopark.in",
  "search_term": "python",
  "total_jobs": 12,
  "jobs": [
    {
      "job_id": "30418",
      "title": "Associate Architect - Python",
      "company": "Techversant Infotech (P) Ltd",
      "company_url": "https://technopark.in/company-details/5730?company=...",
      "detail_url": "https://technopark.in/job-details/30418?job=...",
      "closing_date": "16, June 2026",
      "published_date": "03, June 2026",
      "contact_email": "careers@techversantinfotech.com",
      "career_email": "careers@techversantinfotech.com",
      "description": "...",
      "preferred_skills": "...",
      "location": "Module No:2306, Third Floor, Yamuna, Tower II ...",
      "website": "http://www.techversantinfotech.com"
    }
  ]
}
```

---

### Infopark Jobs
```
GET /infopark/jobs?search=<keyword>&max_jobs=10
```

**Example:**
```bash
curl "http://localhost:8000/infopark/jobs?search=ai&max_jobs=5"
```

**Response:**
```json
{
  "source": "infopark.in",
  "search_term": "ai",
  "total_jobs": 20,
  "jobs": [
    {
      "job_id": "23898",
      "company_id": "109",
      "title": "AI Engineer (1-2 Years)",
      "company": "NewAgeSys Solutions (P) Ltd.",
      "date_of_posting": "03-06-2026",
      "last_date_to_apply": "09 Jun 2026",
      "detail_url": "https://infopark.in/company-jobs/details/23898/109",
      "contact_phone": "0484-2983032",
      "contact_email": "career@newagesysindia.com",
      "career_email": "career@newagesysindia.com",
      "description": "Job Title : AI Engineer ...",
      "location": "Carnival Infopark, Phase 2, Kakkanad, Ernakulam"
    }
  ]
}
```

---

## Query Parameters

| Parameter | Type    | Default | Description                                    |
|-----------|---------|---------|------------------------------------------------|
| `search`  | string  | *required* | Keyword to search (e.g. `python`, `ai`, `react`) |
| `max_jobs`| integer | 10      | Max number of jobs to fetch details for (1–50) |

---

## Interactive Docs

Visit **http://localhost:8000/docs** after starting the server for Swagger UI.

---

## Notes

- Both sites are JavaScript-rendered for listings but their detail pages are server-rendered HTML, making them reliably scrapeable.
- The scraper uses `httpx` async client with realistic browser headers.
- Email extraction uses regex; `career_email` prefers addresses containing keywords like `careers`, `hr`, `recruit`, `jobs`.
- Technopark's listing page (SPA/Next.js) may require an internal API fallback if the static HTML doesn't contain job cards. The scraper tries the JSON API first, then falls back to HTML parsing.