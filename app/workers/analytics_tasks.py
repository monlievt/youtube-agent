"""
app/workers/analytics_tasks.py
Celery tasks untuk penarikan data analytics dan evaluasi.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.queue import UploadQueue
from app.models.analytics import VideoEvaluation
from app.services.analytics_service import AnalyticsService
from app.services.evaluator_service import EvaluatorService
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.analytics_tasks.pull_video_analytics_task")
def pull_video_analytics_task(queue_id: int, log_type: str) -> str:
    """Task untuk menarik data metrics dan membuat log."""
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as session:
            service = AnalyticsService(session)
            evaluator = EvaluatorService(session)
            
            # 1. Tarik & simpan log metrics
            await service.pull_and_log_video_metrics(queue_id, log_type, actor="celery_worker")
            
            # 2. Picu evaluasi performa & diagnosis
            await evaluator.evaluate_video(queue_id, log_type)
            
            await session.commit()
            
    asyncio.run(_run())
    return f"Sukses menarik analytics & evaluasi {log_type} untuk queue_id {queue_id}"


@celery_app.task(name="app.workers.analytics_tasks.schedule_analytics_pulls_task")
def schedule_analytics_pulls_task() -> str:
    """
    Task periodik (Celery Beat) yang memindai video yang sudah di-publish
    dan menjadwalkan penarikan analytics pada umur H+24 dan H+7.
    """
    import asyncio
    
    async def _run():
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            # 1. Pindai untuk H24 (video dipublish 24 jam s/d 36 jam yang lalu)
            h24_start = now - timedelta(hours=36)
            h24_end = now - timedelta(hours=24)
            
            q_h24 = select(UploadQueue).where(
                UploadQueue.status == "DONE",
                UploadQueue.scheduled_time.between(h24_start, h24_end),
                UploadQueue.deleted_at.is_(None)
            )
            res_h24 = await session.execute(q_h24)
            videos_h24 = res_h24.scalars().all()
            
            for video in videos_h24:
                # Cek apakah sudah pernah dievaluasi H24
                q_eval = select(VideoEvaluation).where(
                    VideoEvaluation.queue_id == video.id,
                    VideoEvaluation.eval_stage == "H24"
                )
                res_eval = await session.execute(q_eval)
                if not res_eval.scalar_one_or_none():
                    log.info("scheduling_h24_analytics_pull", queue_id=video.id)
                    pull_video_analytics_task.delay(video.id, "H24")

            # 2. Pindai untuk H7 (video dipublish 7 hari s/d 8 hari yang lalu)
            h7_start = now - timedelta(days=8)
            h7_end = now - timedelta(days=7)
            
            q_h7 = select(UploadQueue).where(
                UploadQueue.status == "DONE",
                UploadQueue.scheduled_time.between(h7_start, h7_end),
                UploadQueue.deleted_at.is_(None)
            )
            res_h7 = await session.execute(q_h7)
            videos_h7 = res_h7.scalars().all()
            
            for video in videos_h7:
                # Cek apakah sudah pernah dievaluasi H7
                q_eval_h7 = select(VideoEvaluation).where(
                    VideoEvaluation.queue_id == video.id,
                    VideoEvaluation.eval_stage == "H7"
                )
                res_eval_h7 = await session.execute(q_eval_h7)
                if not res_eval_h7.scalar_one_or_none():
                    log.info("scheduling_h7_analytics_pull", queue_id=video.id)
                    pull_video_analytics_task.delay(video.id, "H7")
                    
    asyncio.run(_run())
    return "Scan & schedule analytics pulls selesai"


@celery_app.task(name="app.workers.analytics_tasks.sync_channel_metadata_task")
def sync_channel_metadata_task(channel_id: int, actor: str = "SYSTEM") -> str:
    """Task Celery untuk sinkronisasi data profil, statistik dan daftar video channel dari YouTube."""
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as session:
            service = AnalyticsService(session)
            res = await service.sync_channel_metadata(channel_id, actor=actor)
            await session.commit()
            return res
            
    res = asyncio.run(_run())
    return f"Sukses sinkronisasi channel {channel_id}: {res}"

