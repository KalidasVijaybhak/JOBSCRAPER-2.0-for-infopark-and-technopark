# Backwards-compatibility shim — the real app lives in app/main.py
# Run with: uvicorn app.main:app --reload
#       or: python run.py
from app.main import app  # noqa: F401
