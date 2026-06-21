"""
app/workers/upload_tasks.py
Celery tasks: upload execution, stuck detection, quota reset, approval expiry.
"""
import asyncio
import socket
from datetime import datetime, timezone

from app.core.exceptions import QuotaExhaustedError, TokenRevokedError
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.upload_tasks.process_scheduled_uploads", bind=True)
def process_scheduled_uploads(self) -> dict:
    """
    Ambil item SCHEDULED yang waktunya sudah tiba dan upload.
    SELECT FOR UPDATE SKIP LOCKED — aman untuk multi-worker.
    """
    worker_id = f"{socket.gethostname()}-{self.request.id}"

    async def run() -> dict:
        from app.core.database import AsyncSessionLocal
        from app.repositories.queue_repo import QueueRepository
        from app.services.upload_service import UploadService

        uploaded = 0
        quota_exhausted = 0
        errors = 0

        async with AsyncSessionLocal() as session:
            queue_repo = QueueRepository(session)
            upload_service = UploadService(session)

            while True:
                queue_item = await queue_repo.lock_next_scheduled()
                if not queue_item:
                    break

                try:
                    await upload_service.execute_upload(queue_item, worker_id)
                    await session.commit()
                    uploaded += 1

                except QuotaExhaustedError as e:
                    await queue_repo.transition_status(
                        queue_item, "QUOTA_EXHAUSTED",
                        reason=str(e)[:200],
                        actor=f"worker:{worker_id}",
                    )
                    await session.commit()
                    quota_exhausted += 1
                    break  # Stop — quota habis untuk hari ini

                except TokenRevokedError as e:
                    await queue_repo.transition_status(
                        queue_item, "NEEDS_REAUTH",
                        reason=str(e)[:200],
                        actor=f"worker:{worker_id}",
                    )
                    await session.commit()
                    errors += 1

                except Exception as e:
                    # Increment retry atau FAILED_PERMANENT
                    from app.repositories.config_repo import ConfigRepository
                    config_repo = ConfigRepository(session)
                    max_retries = await config_repo.get_int("max_retry_count")

                    queue_item.retry_count += 1
                    queue_item.error_message = str(e)[:500]

                    if queue_item.retry_count >= max_retries:
                        await queue_repo.transition_status(
                            queue_item, "FAILED_PERMANENT",
                            reason=f"Max retries ({max_retries}) tercapai: {str(e)[:200]}",
                            actor=f"worker:{worker_id}",
                        )
                        # Kirim Discord/Telegram Webhook Alert
                        from app.services.alert_service import AlertService
                        alert_service = AlertService()
                        await alert_service.alert_upload_failed(
                            queue_id=queue_item.id,
                            filename=queue_item.staging_path,
                            error_message=str(e)[:200]
                        )
                    else:
                        # Exponential backoff dengan jitter
                        import random
                        delay_seconds = (2 ** queue_item.retry_count) * 60
                        jitter = random.randint(0, 60)
                        from datetime import timedelta
                        queue_item.next_retry_at = (
                            datetime.utcnow() + timedelta(seconds=delay_seconds + jitter)
                        )
                        await queue_repo.transition_status(
                            queue_item, "SCHEDULED",
                            reason=f"Retry {queue_item.retry_count}/{max_retries}: {str(e)[:200]}",
                            actor=f"worker:{worker_id}",
                        )

                    log.error(
                        "upload_task_error",
                        queue_id=queue_item.id,
                        retry_count=queue_item.retry_count,
                        error_type=type(e).__name__,
                        error_message=str(e),
                    )
                    await session.commit()
                    errors += 1

        return {"uploaded": uploaded, "quota_exhausted": quota_exhausted, "errors": errors}

    from app.workers.celery_app import run_async
    result = run_async(run())
    log.info("upload_batch_completed", **result, function="process_scheduled_uploads")
    return result


@celery_app.task(name="app.workers.upload_tasks.detect_stuck_uploads", bind=True)
def detect_stuck_uploads(self) -> dict:
    """
    Deteksi UPLOADING yang stuck lebih dari timeout_minutes.
    Sesuai blueprint F-007.
    """
    async def run() -> dict:
        from app.core.database import AsyncSessionLocal
        from app.repositories.config_repo import ConfigRepository
        from app.repositories.queue_repo import QueueRepository

        stuck_count = 0

        async with AsyncSessionLocal() as session:
            config_repo = ConfigRepository(session)
            queue_repo = QueueRepository(session)

            timeout_minutes = await config_repo.get_int("upload_timeout_minutes")
            stuck_items = await queue_repo.get_stuck_uploading(timeout_minutes)

            for item in stuck_items:
                # TODO: Cek YouTube Studio via API untuk reconciliation
                # Jika video ada: update ke PRIVATE_UPLOADED
                # Jika tidak ada: reset ke SCHEDULED
                log.warning(
                    "stuck_upload_detected",
                    queue_id=item.id,
                    locked_at=str(item.locked_at),
                    worker_id=item.worker_id,
                    function="detect_stuck_uploads",
                )
                await queue_repo.transition_status(
                    item, "FAILED_PERMANENT",
                    reason=f"Upload stuck > {timeout_minutes} menit. Needs manual investigation.",
                    actor="beat:detect_stuck_uploads",
                )
                stuck_count += 1

            await session.commit()

        return {"stuck_detected": stuck_count}

    from app.workers.celery_app import run_async
    return run_async(run())


@celery_app.task(name="app.workers.upload_tasks.cancel_expired_approvals", bind=True)
def cancel_expired_approvals(self) -> dict:
    """Auto soft-delete AWAITING_APPROVAL yang expired sesuai approval_timeout_days."""
    async def run() -> dict:
        from datetime import datetime
        from app.core.database import AsyncSessionLocal
        from app.repositories.config_repo import ConfigRepository
        from app.repositories.queue_repo import QueueRepository

        cancelled = 0

        async with AsyncSessionLocal() as session:
            config_repo = ConfigRepository(session)
            queue_repo = QueueRepository(session)

            timeout_days = await config_repo.get_int("approval_timeout_days")
            expired_items = await queue_repo.get_pending_approval_expired(timeout_days)

            for item in expired_items:
                item.deleted_at = datetime.utcnow()
                await queue_repo.transition_status(
                    item, "FAILED_PERMANENT",
                    reason=f"AWAITING_APPROVAL expired setelah {timeout_days} hari",
                    actor="beat:cancel_expired_approvals",
                )
                cancelled += 1
                log.info(
                    "approval_expired_cancelled",
                    queue_id=item.id,
                    function="cancel_expired_approvals",
                )

            await session.commit()

        return {"cancelled": cancelled}

    from app.workers.celery_app import run_async
    return run_async(run())


@celery_app.task(name="app.workers.upload_tasks.reset_daily_quota", bind=True)
def reset_daily_quota(self) -> dict:
    """Reset quota harian di tengah malam UTC."""
    async def run() -> dict:
        from datetime import date
        from sqlalchemy import update
        from app.core.database import AsyncSessionLocal
        from app.models.system import GcpQuotaTracker

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(GcpQuotaTracker).values(
                    units_used_today=0,
                    reset_date=date.today(),
                )
            )
            await session.commit()

        log.info("daily_quota_reset", function="reset_daily_quota")
        return {"status": "reset_completed"}

    from app.workers.celery_app import run_async
    return run_async(run())


@celery_app.task(name="app.workers.upload_tasks.worker_heartbeat_task")
def worker_heartbeat_task() -> str:
    """Task periodik untuk menulis timestamp keaktifan worker ke Redis."""
    import redis
    import time
    from app.core.config import get_settings
    
    settings = get_settings()
    # Gunakan client redis sync biasa
    r = redis.Redis.from_url(settings.redis_url)
    current_time = int(time.time())
    r.set("hermes:worker:heartbeat", current_time)
    log.info("worker_heartbeat_recorded", timestamp=current_time)
    return f"Heartbeat recorded: {current_time}"

