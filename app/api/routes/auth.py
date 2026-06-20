"""
app/api/routes/auth.py
OAuth 2.0 flow untuk onboarding channel YouTube.
Step 1: GET /auth/youtube/{channel_id} → authorization URL
Step 2: GET /auth/youtube/{channel_id}/callback → simpan token

Konfigurasi credentials (pilih salah satu, prioritas dari atas ke bawah):
  1. File client_secrets.json di root project (dihasilkan dari Google Cloud Console)
  2. Env vars GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET di .env
"""
import json
import os
from pathlib import Path

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

# Path ke client_secrets.json — dicari di beberapa lokasi
# /app/client_secrets.json: standar di dalam Docker container
# Path relatif ke file ini (naik 3 level ke root project): untuk development lokal
_SEARCH_PATHS = [
    Path("/app/client_secrets.json"),                         # Docker
    Path(__file__).resolve().parent.parent.parent.parent / "client_secrets.json",  # Dev
]
_CLIENT_SECRETS_PATH = next((p for p in _SEARCH_PATHS if p.exists()), None)


def _get_client_config(redirect_uri: str) -> dict:
    """
    Baca OAuth client config dari client_secrets.json atau env vars.
    Prioritas: file JSON > env vars.
    Raise HTTPException 500 jika tidak ada konfigurasi yang valid.
    """
    # Opsi 1: client_secrets.json (standar Google)
    if _CLIENT_SECRETS_PATH is not None:
        with open(_CLIENT_SECRETS_PATH) as f:
            secrets = json.load(f)
        # Format Google: {"web": {"client_id": ..., "client_secret": ..., ...}}
        web = secrets.get("web") or secrets.get("installed")
        if not web:
            raise HTTPException(
                status_code=500,
                detail="client_secrets.json tidak valid — key 'web' atau 'installed' tidak ditemukan",
            )
        return {
            "web": {
                "client_id": web["client_id"],
                "client_secret": web["client_secret"],
                "redirect_uris": [redirect_uri],
                "auth_uri": web.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": web.get("token_uri", "https://oauth2.googleapis.com/token"),
            }
        }

    # Opsi 2: env vars
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                "Google OAuth belum dikonfigurasi. "
                "Letakkan file client_secrets.json di root project, "
                "atau set env vars GOOGLE_CLIENT_ID dan GOOGLE_CLIENT_SECRET."
            ),
        )

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# Temporary state store (in-memory — OK untuk 1 orang, single server)
_pending_flows: dict[str, dict] = {}


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

    # Bangun redirect_uri dengan benar meskipun di belakang reverse proxy (Nginx + SSL)
    # Gunakan APP_BASE_URL dari .env jika diset, agar redirect_uri selalu https:// di production.
    callback_path = request.url_for("oauth_callback").path
    if settings.app_base_url:
        redirect_uri = f"{settings.app_base_url.rstrip('/')}{callback_path}"
    else:
        redirect_uri = str(request.url_for("oauth_callback"))

    client_config = _get_client_config(redirect_uri)
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Simpan flow beserta channel_id terkait
    _pending_flows[state] = {"flow": flow, "channel_id": channel_id}

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
    "/youtube/callback",
    name="oauth_callback",
    summary="Step 2: Callback dari Google — simpan token, redirect ke dashboard",
    response_class=RedirectResponse,
    include_in_schema=False,
)
async def oauth_callback(
    code: str,
    state: str,
    db: DBSession,
    request: Request,
):
    """
    Handle callback dari Google OAuth secara terpusat (statis).
    Exchange code → token → enkripsi → simpan ke DB → redirect ke /channels.
    """
    flow_data = _pending_flows.pop(state, None)
    if not flow_data:
        return RedirectResponse(
            url="/channels?oauth=error&msg=State+tidak+valid+atau+expired",
            status_code=303,
        )

    flow = flow_data["flow"]
    channel_id = flow_data["channel_id"]

    # Harus identik dengan redirect_uri yang dipakai di start_oauth
    callback_path = request.url_for("oauth_callback").path
    if settings.app_base_url:
        redirect_uri = f"{settings.app_base_url.rstrip('/')}{callback_path}"
    else:
        redirect_uri = str(request.url_for("oauth_callback"))
    flow.redirect_uri = redirect_uri

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        log.error("oauth_callback_failed", channel_id=channel_id, error=str(e))
        return RedirectResponse(
            url=f"/channels?oauth=error&msg=Token+exchange+gagal",
            status_code=303,
        )

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

    # Memicu sync data awal (initial sync) YouTube
    try:
        from app.workers.analytics_tasks import sync_channel_metadata_task
        sync_channel_metadata_task.delay(channel_id, actor="oauth_callback")
        log.info("initial_channel_sync_triggered", channel_id=channel_id)
    except Exception as e:
        log.error("failed_to_trigger_initial_sync", channel_id=channel_id, error=str(e))

    log.info(
        "oauth_completed",
        channel_id=channel_id,
        function="oauth_callback",
    )

    # Redirect ke halaman channels dengan notifikasi sukses
    return RedirectResponse(
        url=f"/channels?oauth=success&channel_id={channel_id}",
        status_code=303,
    )
