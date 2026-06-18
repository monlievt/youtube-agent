"""
app/api/routes/auth.py
OAuth 2.0 flow untuk onboarding channel YouTube.
Step 1: GET /auth/youtube/{channel_id} → authorization URL
Step 2: GET /auth/youtube/{channel_id}/callback → simpan token
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from app.api.dependencies import CurrentUser, DBSession
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories.channel_repo import ChannelRepository
from app.services.credential_service import CredentialService

log = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# Temporary state store (in-memory — OK untuk 1 orang, single server)
_pending_flows: dict[str, Flow] = {}


@router.get(
    "/youtube/{channel_id}",
    summary="Step 1: Mulai OAuth flow — return authorization URL",
)
async def start_oauth(
    channel_id: int,
    db: DBSession,
    user: CurrentUser,
    request: Request,
) -> dict:
    """
    Return URL yang harus dibuka user di browser untuk authorize YouTube access.
    """
    channel_repo = ChannelRepository(db)
    channel = await channel_repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} tidak ditemukan")

    redirect_uri = str(request.url_for("oauth_callback", channel_id=channel_id))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": "PLACEHOLDER_CLIENT_ID",  # Akan diisi saat setup
                "client_secret": "PLACEHOLDER_CLIENT_SECRET",
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    _pending_flows[state] = flow

    log.info(
        "oauth_started",
        channel_id=channel_id,
        state=state[:8],
        function="start_oauth",
    )

    return {
        "channel_id": channel_id,
        "channel_name": channel.channel_name,
        "authorization_url": authorization_url,
        "instruction": "Buka authorization_url di browser, authorize, lalu paste callback URL yang di-redirect",
    }


@router.get(
    "/youtube/{channel_id}/callback",
    name="oauth_callback",
    summary="Step 2: Callback dari Google — simpan token",
)
async def oauth_callback(
    channel_id: int,
    code: str,
    state: str,
    db: DBSession,
    request: Request,
) -> dict:
    """
    Handle callback dari Google OAuth.
    Exchange code → token → enkripsi → simpan ke DB.
    """
    flow = _pending_flows.pop(state, None)
    if not flow:
        raise HTTPException(status_code=400, detail="State tidak valid atau expired")

    redirect_uri = str(request.url_for("oauth_callback", channel_id=channel_id))
    flow.redirect_uri = redirect_uri

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        log.error("oauth_callback_failed", channel_id=channel_id, error=str(e))
        raise HTTPException(status_code=400, detail=f"Token exchange gagal: {e}")

    credentials = flow.credentials
    credential_service = CredentialService(db)

    await credential_service.save_credentials(
        channel_id=channel_id,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        refresh_token=credentials.refresh_token,
        actor="oauth_flow",
        ip_address=request.client.host if request.client else None,
    )

    # Update auth_status ke VALID
    channel_repo = ChannelRepository(db)
    await channel_repo.set_auth_status(channel_id, "VALID")

    log.info(
        "oauth_completed",
        channel_id=channel_id,
        function="oauth_callback",
    )

    return {
        "status": "success",
        "channel_id": channel_id,
        "message": "Token berhasil disimpan. Channel siap digunakan.",
    }
