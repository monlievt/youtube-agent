"""
app/api/dependencies.py
FastAPI dependencies — DB session, auth, dll.
"""
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.encryption import decrypt

settings = get_settings()
security = HTTPBasic(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    """
    Mendukung cookie-based auth (untuk dashboard browser) dan HTTP Basic Auth (untuk API client).
    """
    # 1. Coba dari Cookie
    session_cookie = request.cookies.get("hermes_session")
    if session_cookie:
        try:
            username = decrypt(session_cookie)
            if username == settings.dashboard_username:
                return username
        except Exception:
            pass

    # 2. Coba dari Basic Auth
    if credentials:
        correct_username = secrets.compare_digest(
            credentials.username.encode("utf-8"),
            settings.dashboard_username.encode("utf-8"),
        )
        correct_password = secrets.compare_digest(
            credentials.password.encode("utf-8"),
            settings.dashboard_password.encode("utf-8"),
        )
        if correct_username and correct_password:
            return credentials.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Basic"},
    )


async def get_current_user_page(request: Request) -> str:
    """
    Dependency untuk halaman HTML. Redirect ke /login jika tidak ada session.
    """
    session_cookie = request.cookies.get("hermes_session")
    if session_cookie:
        try:
            username = decrypt(session_cookie)
            if username == settings.dashboard_username:
                return username
        except Exception:
            pass
            
    # Redirect ke halaman login
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"},
    )


# Type aliases untuk convenience
DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[str, Depends(get_current_user)]
CurrentPageUser = Annotated[str, Depends(get_current_user_page)]

