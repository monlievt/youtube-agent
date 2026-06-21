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

    async def sync_channel_metadata(self, channel_id: int, actor: str = "SYSTEM") -> dict:
        """
        Tarik info channel dari YouTube API (nama, avatar, subscribers, views, video_count, video cache)
        dan update ke database.
        """
        from app.repositories.channel_repo import ChannelRepository
        from app.gateways.youtube_gateway import YouTubeGateway
        import json

        channel_repo = ChannelRepository(self._session)
        channel = await channel_repo.get_by_id(channel_id)
        if not channel:
            raise ValueError(f"Channel ID {channel_id} tidak ditemukan")

        # Ambil credentials
        client_id, client_secret, refresh_token = (
            await self._credential_service.get_decrypted_credentials(
                channel_id, actor=actor
            )
        )

        yt = YouTubeGateway(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            channel_id=channel_id,
        )

        # 1. Fetch channel info
        ch_info = yt.get_channel_info()
        snippet = ch_info.get("snippet", {})
        statistics = ch_info.get("statistics", {})
        content_details = ch_info.get("contentDetails", {})

        # Extract values
        yt_channel_id = ch_info.get("id")
        yt_title = snippet.get("title")
        thumbnail_url = snippet.get("thumbnails", {}).get("default", {}).get("url")
        if not thumbnail_url:
            thumbnail_url = snippet.get("thumbnails", {}).get("medium", {}).get("url")

        subscribers = int(statistics.get("subscriberCount", 0))
        views = int(statistics.get("viewCount", 0))
        video_count = int(statistics.get("videoCount", 0))

        # 2. Fetch upload playlist items to get recent videos
        uploads_playlist_id = content_details.get("relatedPlaylists", {}).get("uploads")
        recent_videos = []
        if uploads_playlist_id:
            try:
                playlist_items = yt.get_playlist_items(uploads_playlist_id, max_results=50)
                for item in playlist_items:
                    item_snippet = item.get("snippet", {})
                    v_id = item_snippet.get("resourceId", {}).get("videoId")
                    v_title = item_snippet.get("title")
                    v_desc = item_snippet.get("description")
                    v_published_at = item_snippet.get("publishedAt")
                    if v_id:
                        recent_videos.append({
                            "youtube_video_id": v_id,
                            "title": v_title,
                            "description": (v_desc[:200] + "...") if v_desc and len(v_desc) > 200 else (v_desc or ""),
                            "published_at": v_published_at,
                        })
            except Exception as e:
                log.error("sync_playlist_items_failed", channel_id=channel_id, error=str(e))

        # Update channel model
        channel.youtube_channel_id = yt_channel_id
        if yt_title:
            channel.channel_name = yt_title
        channel.youtube_thumbnail_url = thumbnail_url
        channel.youtube_subscribers = subscribers
        channel.youtube_views = views
        channel.youtube_video_count = video_count
        channel.youtube_videos_cache = json.dumps(recent_videos)

        await self._session.flush()

        log.info(
            "channel_metadata_synced",
            channel_id=channel_id,
            title=yt_title,
            subscribers=subscribers,
            views=views,
            video_count=video_count,
            recent_videos_count=len(recent_videos),
        )

        return {
            "status": "success",
            "youtube_channel_id": yt_channel_id,
            "title": yt_title,
            "thumbnail_url": thumbnail_url,
            "subscribers": subscribers,
            "views": views,
            "video_count": video_count,
            "synced_videos_count": len(recent_videos),
        }
