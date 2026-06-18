"""
app/services/analytics_service.py
Service untuk orkestrasi penarikan data analytics dan memicu evaluasi performa.
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.gateways.analytics_gateway import YouTubeAnalyticsGateway
from app.models.analytics import AnalyticsLog
from app.repositories.analytics_repo import AnalyticsRepository
from app.repositories.queue_repo import QueueRepository
from app.services.credential_service import CredentialService

log = get_logger(__name__)


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._analytics_repo = AnalyticsRepository(session)
        self._queue_repo = QueueRepository(session)
        self._credential_service = CredentialService(session)

    async def pull_and_log_video_metrics(
        self, queue_id: int, log_type: str, actor: str = "SYSTEM"
    ) -> AnalyticsLog:
        """
        Ambil metrics video dari YouTube API, simpan ke database (analytics_logs),
        dan kembalikan log record-nya.
        """
        queue_item = await self._queue_repo.get_by_id(queue_id)
        if not queue_item or not queue_item.youtube_video_id:
            raise ValueError(f"Queue item {queue_id} tidak valid atau belum di-upload ke YouTube")

        channel_id = queue_item.channel_id
        youtube_video_id = queue_item.youtube_video_id

        # Ambil credentials untuk API gateway
        client_id, client_secret, refresh_token = (
            await self._credential_service.get_decrypted_credentials(
                channel_id, actor=actor
            )
        )

        gateway = YouTubeAnalyticsGateway(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            channel_id=channel_id,
        )

        # Tarik data dari YouTube
        metrics = gateway.pull_video_analytics(youtube_video_id)

        # Simpan ke logs
        analytics_log = AnalyticsLog(
            youtube_video_id=youtube_video_id,
            channel_id=channel_id,
            log_type=log_type,
            views=metrics["views"],
            impressions=metrics["impressions"],
            ctr_percentage=metrics["ctr_percentage"],
            avd_seconds=metrics["avd_seconds"],
            likes=metrics["likes"],
        )

        saved_log = await self._analytics_repo.save_analytics_log(analytics_log)

        log.info(
            "analytics_log_saved",
            queue_id=queue_id,
            youtube_video_id=youtube_video_id,
            log_type=log_type,
            views=metrics["views"],
            ctr=metrics["ctr_percentage"],
            avd=metrics["avd_seconds"],
        )

        return saved_log
