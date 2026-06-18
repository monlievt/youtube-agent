"""
app/repositories/analytics_repo.py
Repository untuk Tier 2: analytics_logs, video_evaluations, timeslot_performance, thumbnail_styles.
"""
from datetime import datetime
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analytics import (
    AnalyticsLog,
    VideoEvaluation,
    EvaluationOption,
    TimeslotPerformance,
    ThumbnailStyle,
)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_analytics_log(self, log: AnalyticsLog) -> AnalyticsLog:
        self._session.add(log)
        await self._session.flush()
        await self._session.refresh(log)
        return log

    async def create_evaluation(self, evaluation: VideoEvaluation) -> VideoEvaluation:
        self._session.add(evaluation)
        await self._session.flush()
        await self._session.refresh(evaluation)
        return evaluation

    async def get_evaluation_by_id(self, eval_id: int) -> VideoEvaluation | None:
        result = await self._session.execute(
            select(VideoEvaluation)
            .options(selectinload(VideoEvaluation.options), selectinload(VideoEvaluation.queue_item))
            .where(VideoEvaluation.id == eval_id, VideoEvaluation.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_evaluations_by_status(self, status: str) -> list[VideoEvaluation]:
        result = await self._session.execute(
            select(VideoEvaluation)
            .options(selectinload(VideoEvaluation.options), selectinload(VideoEvaluation.queue_item))
            .where(VideoEvaluation.eval_status == status, VideoEvaluation.deleted_at.is_(None))
            .order_by(VideoEvaluation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_all_active_evaluations(self) -> list[VideoEvaluation]:
        result = await self._session.execute(
            select(VideoEvaluation)
            .options(selectinload(VideoEvaluation.options), selectinload(VideoEvaluation.queue_item))
            .where(
                VideoEvaluation.eval_status.in_(["PENDING", "ACTION_REQUIRED"]),
                VideoEvaluation.deleted_at.is_(None)
            )
            .order_by(VideoEvaluation.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_channel_baseline(self, channel_id: int, log_type: str) -> tuple[float, float]:
        """
        Hitung baseline (rata-rata CTR dan AVD) untuk channel_id pada log_type tertentu (misal H24).
        """
        result = await self._session.execute(
            select(
                func.avg(AnalyticsLog.ctr_percentage),
                func.avg(AnalyticsLog.avd_seconds)
            )
            .where(
                AnalyticsLog.channel_id == channel_id,
                AnalyticsLog.log_type == log_type
            )
        )
        avg_ctr, avg_avd = result.fetchone() or (None, None)
        return float(avg_ctr or 0.0), float(avg_avd or 0.0)

    async def get_timeslot_performance(self, channel_id: int, dow: int, hour: int) -> TimeslotPerformance | None:
        result = await self._session.execute(
            select(TimeslotPerformance)
            .where(
                TimeslotPerformance.channel_id == channel_id,
                TimeslotPerformance.day_of_week == dow,
                TimeslotPerformance.hour_of_day == hour
            )
        )
        return result.scalar_one_or_none()

    async def save_timeslot_performance(self, perf: TimeslotPerformance) -> TimeslotPerformance:
        self._session.add(perf)
        await self._session.flush()
        return perf

    async def get_thumbnail_style(self, channel_id: int, style_name: str) -> ThumbnailStyle | None:
        result = await self._session.execute(
            select(ThumbnailStyle)
            .where(
                ThumbnailStyle.channel_id == channel_id,
                ThumbnailStyle.style_name == style_name,
                ThumbnailStyle.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def save_thumbnail_style(self, style: ThumbnailStyle) -> ThumbnailStyle:
        self._session.add(style)
        await self._session.flush()
        return style
