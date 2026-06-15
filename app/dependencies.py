import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Inject the shared AsyncClient created during app startup."""
    return request.app.state.http_client
