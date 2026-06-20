"""
app/gateways/youtube_gateway.py
YouTube Data API v3 adapter.
Internal code TIDAK import google library langsung — semua lewat sini.
Sesuai blueprint: layer Gateway = External API only, circuit breaker di sini.
"""
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.core.exceptions import (
    ExternalAPIError,
    QuotaExhaustedError,
    TokenRevokedError,
)
from app.core.logging import get_logger

log = get_logger(__name__)

YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"


class YouTubeGateway:
    """
    Adapter untuk YouTube Data API v3.
    Semua operasi YouTube melewati class ini.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: int,
    ):
        self._channel_id = channel_id
        self._credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        self._service = build(
            YOUTUBE_API_SERVICE,
            YOUTUBE_API_VERSION,
            credentials=self._credentials,
            cache_discovery=False,
        )

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        category_id: str = "10",  # 10 = Music
    ) -> str:
        """
        Upload video sebagai PRIVATE dengan publishAt=null.
        Return: youtube_video_id.
        Upload 1650 quota units.
        """
        log.info(
            "youtube_upload_started",
            channel_id=self._channel_id,
            video_path=video_path,
            agent="youtube_gateway",
            function="upload_video",
        )

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/*",
            resumable=True,
        )

        try:
            request = self._service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = None
            while response is None:
                _, response = request.next_chunk()

            video_id = response["id"]
            log.info(
                "youtube_upload_done",
                channel_id=self._channel_id,
                youtube_video_id=video_id,
                agent="youtube_gateway",
            )
            return video_id

        except HttpError as e:
            self._handle_http_error(e, "upload_video")

    def upload_thumbnail(self, youtube_video_id: str, thumbnail_path: str) -> None:
        """Upload thumbnail ke video yang sudah di-upload."""
        log.info(
            "youtube_thumbnail_upload_started",
            channel_id=self._channel_id,
            youtube_video_id=youtube_video_id,
        )
        try:
            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            self._service.thumbnails().set(
                videoId=youtube_video_id,
                media_body=media,
            ).execute()
            log.info(
                "youtube_thumbnail_upload_done",
                youtube_video_id=youtube_video_id,
            )
        except HttpError as e:
            self._handle_http_error(e, "upload_thumbnail")

    def set_scheduled(self, youtube_video_id: str, publish_at: datetime) -> None:
        """
        Set video menjadi scheduled (akan publish otomatis pada publish_at).
        publish_at harus dalam format ISO 8601 dengan timezone.
        """
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=timezone.utc)

        publish_at_str = publish_at.isoformat()

        log.info(
            "youtube_schedule_started",
            youtube_video_id=youtube_video_id,
            publish_at=publish_at_str,
        )

        try:
            self._service.videos().update(
                part="status",
                body={
                    "id": youtube_video_id,
                    "status": {
                        "privacyStatus": "scheduled",
                        "publishAt": publish_at_str,
                    },
                },
            ).execute()
            log.info(
                "youtube_schedule_done",
                youtube_video_id=youtube_video_id,
                publish_at=publish_at_str,
            )
        except HttpError as e:
            self._handle_http_error(e, "set_scheduled")

    def get_channel_info(self) -> dict:
        """Verify token bisa digunakan — ambil info channel, statistics, dan playlist uploads."""
        try:
            response = self._service.channels().list(
                part="snippet,statistics,contentDetails",
                mine=True,
            ).execute()
            items = response.get("items", [])
            if not items:
                raise ExternalAPIError("Tidak ada channel yang terkoneksi dengan token ini")
            return items[0]
        except HttpError as e:
            self._handle_http_error(e, "get_channel_info")

    def get_playlist_items(self, playlist_id: str, max_results: int = 50) -> list[dict]:
        """Ambil daftar item (video) dari playlist tertentu (misal: playlist uploads)."""
        try:
            response = self._service.playlistItems().list(
                part="snippet,status",
                playlistId=playlist_id,
                maxResults=max_results,
            ).execute()
            return response.get("items", [])
        except HttpError as e:
            self._handle_http_error(e, "get_playlist_items")

    def _handle_http_error(self, error: HttpError, operation: str) -> None:
        """Konversi HttpError ke domain exceptions."""
        status_code = error.resp.status
        reason = ""

        try:
            import json
            error_content = json.loads(error.content)
            reason = error_content.get("error", {}).get("errors", [{}])[0].get("reason", "")
        except Exception:
            pass

        log.error(
            "youtube_api_error",
            operation=operation,
            channel_id=self._channel_id,
            http_status=status_code,
            reason=reason,
            error_message=str(error),
        )

        if status_code == 401 or reason == "invalid_grant":
            raise TokenRevokedError(
                f"Token revoked untuk channel {self._channel_id}. Re-auth diperlukan.",
                status_code=status_code,
            )
        elif status_code == 403 and reason == "quotaExceeded":
            raise QuotaExhaustedError(
                "YouTube API quota habis. Tunggu reset (tengah malam Pacific Time).",
                status_code=status_code,
            )
        else:
            raise ExternalAPIError(
                f"YouTube API error pada {operation}: {error}",
                status_code=status_code,
            )
