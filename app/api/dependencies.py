"""
app/api/dependencies.py
FastAPI dependencies — DB session, auth, dll.

Auth Strategy (unified, no double login):
- Dashboard pages  → cookie session (hermes_session) → redirect /login jika tidak ada
- API endpoints    → cookie session ATAU Bearer token (API_BEARER_TOKEN env var)
- Tidak ada HTTP Basic Auth → tidak ada browser native popup
"""
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.encryption import decrypt
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


def _verify_session_cookie(request: Request) -> str | None:
    """
    Verifikasi cookie session hermes_session.
    Return username jika valid, None jika tidak.
    """
    session_cookie = request.cookies.get("hermes_session")
    if not session_cookie:
        return None
    try:
        username = decrypt(session_cookie)
        if username == settings.dashboard_username:
            return username
    except Exception:
        pass
    return None


def _verify_bearer_token(request: Request) -> str | None:
    """
    Verifikasi Bearer token dari Authorization header.
    Hanya aktif jika API_BEARER_TOKEN dikonfigurasi di env.
    Return username jika valid, None jika tidak.
    """
    bearer_token = settings.api_bearer_token
    if not bearer_token:
        return None  # Bearer token tidak dikonfigurasi, skip

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    provided_token = auth_header[len("Bearer "):]
    if secrets.compare_digest(provided_token.encode(), bearer_token.encode()):
        return settings.dashboard_username

    return None


async def get_current_user(request: Request) -> str:
    """
    Dependency untuk API endpoints (/api/*).
    Cek: cookie session → Bearer token → redirect /login (bukan 401 popup).

    Tidak menggunakan HTTPBasic → tidak ada browser native popup.
    """
    # 1. Cookie session (browser dashboard)
    username = _verify_session_cookie(request)
    if username:
        return username

    # 2. Bearer token (API client / curl / script)
    username = _verify_bearer_token(request)
    if username:
        return username

    # 3. Tidak ada auth yang valid
    # Cek apakah request dari browser (Accept: text/html) atau API client
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        # Browser: redirect ke login page
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )

    # API client: kembalikan 401 JSON (tanpa WWW-Authenticate: Basic agar tidak trigger popup)
    log.warning(
        "api_unauthorized",
        path=str(request.url.path),
        ip=request.client.host if request.client else "unknown",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a valid session cookie or Bearer token.",
    )


async def get_current_user_page(request: Request) -> str:
    """
    Dependency untuk halaman HTML dashboard.
    Selalu redirect ke /login jika tidak ada session yang valid.
    """
    username = _verify_session_cookie(request)
    if username:
        return username

    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"},
    )


# Type aliases untuk convenience
DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[str, Depends(get_current_user)]
CurrentPageUser = Annotated[str, Depends(get_current_user_page)]
