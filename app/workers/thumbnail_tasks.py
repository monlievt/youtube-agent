"""
app/workers/thumbnail_tasks.py
Celery task: generate thumbnail untuk item METADATA_READY.
"""
import asyncio
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)
settings = get_settings()


@celery_app.task(name="app.workers.thumbnail_tasks.generate_thumbnail_for_queue", bind=True)
def generate_thumbnail_for_queue(self, queue_id: int) -> dict:
    """Generate thumbnail untuk satu queue item."""

    async def run() -> dict:
        from app.core.database import AsyncSessionLocal
        from app.repositories.queue_repo import QueueRepository
        from app.services.thumbnail_service import ThumbnailService

        templates_dir = str(Path(settings.nfs_thumbnails_path) / "templates")

        async with AsyncSessionLocal() as session:
            queue_repo = QueueRepository(session)
            thumbnail_service = ThumbnailService(templates_dir=templates_dir)

            queue_item = await queue_repo.get_by_id(queue_id)
            if not queue_item:
                return {"status": "not_found", "queue_id": queue_id}

            channel = queue_item.channel
            genre = channel.genre if channel else "default"

            try:
                # Extract frame
                frame_path = thumbnail_service.extract_frame(queue_item.staging_path)

                # Load template
                template_path = thumbnail_service.load_template(
                    channel_id=queue_item.channel_id,
                    genre=genre,
                )

                # Output path
                output_dir = Path(settings.nfs_thumbnails_path) / channel.channel_name
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / f"{queue_id}.jpg")

                # Generate thumbnail
                thumbnail_service.create_thumbnail(
                    frame_path=frame_path,
                    template_path=template_path,
                    title=queue_item.title_final or "",
                    output_path=output_path,
                )

                # Cleanup temp frame
                if os.path.exists(frame_path):
                    os.unlink(frame_path)

                # Update queue item
                queue_item.thumbnail_path = output_path
                await session.flush()
                await session.commit()

                log.info(
                    "thumbnail_task_done",
                    queue_id=queue_id,
                    output_path=output_path,
                    function="generate_thumbnail_for_queue",
                )
                return {"status": "done", "queue_id": queue_id, "thumbnail_path": output_path}

            except Exception as e:
                log.error(
                    "thumbnail_task_failed",
                    queue_id=queue_id,
                    error_type=type(e).__name__,
                    error_message=str(e),
                )
                # Jangan fail seluruh upload — thumbnail gagal bisa di-retry manual
                return {"status": "failed", "queue_id": queue_id, "error": str(e)}

    from app.workers.celery_app import run_async
    return run_async(run())

