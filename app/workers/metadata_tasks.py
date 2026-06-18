"""
app/workers/metadata_tasks.py
Celery task: generate metadata AI untuk item PENDING.
SELECT FOR UPDATE SKIP LOCKED untuk anti race condition.
"""
import asyncio

from app.core.exceptions import MetadataValidationError
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.metadata_tasks.process_pending_metadata", bind=True)
def process_pending_metadata(self) -> dict:
    """
    Proses semua item PENDING untuk generate metadata.
    Satu batch per run, SKIP LOCKED untuk multi-worker.
    """

    async def run() -> dict:
        from app.core.database import AsyncSessionLocal
        from app.repositories.queue_repo import QueueRepository
        from app.services.metadata_service import MetadataService
        from app.services.scheduler_service import SchedulerService

        processed = 0
        failed = 0

        async with AsyncSessionLocal() as session:
            queue_repo = QueueRepository(session)
            metadata_service = MetadataService(session)
            scheduler_service = SchedulerService(session)

            # Ambil semua PENDING dan proses satu per satu
            while True:
                queue_item = await queue_repo.lock_next_pending()
                if not queue_item:
                    break

                try:
                    # Generate metadata
                    metadata = await metadata_service.generate_for_queue_item(queue_item)
                    await metadata_service.save_metadata_to_queue(queue_item, metadata)

                    # Tentukan slot waktu
                    scheduled_time = await scheduler_service.get_next_slot(queue_item.channel_id)
                    queue_item.scheduled_time = scheduled_time
                    queue_item.actual_publish_hour = scheduled_time.hour
                    queue_item.actual_publish_dow = scheduled_time.weekday()
                    await session.flush()

                    # Transisi berdasarkan trust level channel
                    channel = queue_item.channel
                    if channel and channel.trust_level == "TRUSTED":
                        await queue_repo.transition_status(
                            queue_item, "SCHEDULED",
                            reason="Auto-scheduled (TRUSTED channel)",
                            actor="metadata_worker",
                        )
                    else:
                        await queue_repo.transition_status(
                            queue_item, "AWAITING_APPROVAL",
                            reason="Awaiting human approval (NEW channel)",
                            actor="metadata_worker",
                        )

                    await session.commit()
                    processed += 1

                    log.info(
                        "metadata_task_done",
                        queue_id=queue_item.id,
                        status=queue_item.status,
                        function="process_pending_metadata",
                    )

                except MetadataValidationError as e:
                    log.error(
                        "metadata_validation_failed_permanent",
                        queue_id=queue_item.id,
                        error_message=str(e),
                    )
                    await queue_repo.transition_status(
                        queue_item, "FAILED_PERMANENT",
                        reason=f"Metadata validation failed: {str(e)[:200]}",
                        actor="metadata_worker",
                    )
                    queue_item.error_message = str(e)[:500]
                    await session.commit()
                    failed += 1

                except Exception as e:
                    log.error(
                        "metadata_task_error",
                        queue_id=queue_item.id,
                        error_type=type(e).__name__,
                        error_message=str(e),
                    )
                    # Set PAUSED_EXTERNAL jika OpenRouter down
                    await queue_repo.transition_status(
                        queue_item, "PAUSED_EXTERNAL",
                        reason=str(e)[:200],
                        actor="metadata_worker",
                    )
                    await session.commit()
                    failed += 1

        return {"processed": processed, "failed": failed}

    result = asyncio.run(run())
    log.info("metadata_batch_completed", **result, function="process_pending_metadata")
    return result
