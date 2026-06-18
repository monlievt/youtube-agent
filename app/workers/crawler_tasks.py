"""
app/workers/crawler_tasks.py
Celery task: scan NFS storage untuk file baru.
Sesuai blueprint Tahap 1: Ingest (setiap 1 jam via Celery Beat).
"""
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import DuplicateFileError, NFSUnavailableError
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)
settings = get_settings()

NFS_HEALTH_FILE = ".nfs_check"
SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


@celery_app.task(name="app.workers.crawler_tasks.scan_omv_storage", bind=True)
def scan_omv_storage(self) -> dict:
    """
    Scan /mnt/omv-videos/ untuk file baru per channel.
    Jika NFS down: log WARNING, skip (tidak crash).
    """
    import asyncio
    from app.core.database import AsyncSessionLocal
    from app.repositories.channel_repo import ChannelRepository
    from app.services.upload_service import UploadService

    log.info("crawler_scan_started", function="scan_omv_storage", agent="crawler")

    # Health check NFS
    nfs_path = Path(settings.nfs_videos_path)
    health_file = nfs_path / NFS_HEALTH_FILE

    if not nfs_path.exists():
        log.warning(
            "nfs_unavailable",
            nfs_path=str(nfs_path),
            reason="Path tidak ada",
            function="scan_omv_storage",
        )
        return {"status": "skipped", "reason": "NFS unavailable"}

    if not health_file.exists():
        # Buat health file jika belum ada
        try:
            health_file.touch()
        except OSError:
            log.warning(
                "nfs_health_check_failed",
                nfs_path=str(nfs_path),
                function="scan_omv_storage",
            )
            return {"status": "skipped", "reason": "NFS health check failed"}

    processed = 0
    skipped = 0
    errors = 0

    async def run() -> None:
        nonlocal processed, skipped, errors

        async with AsyncSessionLocal() as session:
            channel_repo = ChannelRepository(session)
            upload_service = UploadService(session)

            channels = await channel_repo.get_all_active()

            for channel in channels:
                channel_dir = nfs_path / channel.channel_name
                if not channel_dir.exists():
                    log.info(
                        "channel_dir_not_found",
                        channel_name=channel.channel_name,
                        path=str(channel_dir),
                    )
                    continue

                for file_path in channel_dir.iterdir():
                    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue

                    try:
                        await upload_service.ingest_file(
                            channel_id=channel.id,
                            nfs_file_path=str(file_path),
                        )
                        processed += 1

                        # Write audit log
                        await channel_repo.write_audit_log(
                            actor="crawler",
                            action="file_ingested",
                            resource_type="upload_queue",
                            resource_id=str(channel.id),
                            details={
                                "filename": file_path.name,
                                "channel": channel.channel_name,
                            },
                        )
                        await session.commit()

                    except DuplicateFileError:
                        skipped += 1
                        # Log duplicate ke audit log
                        await channel_repo.write_audit_log(
                            actor="crawler",
                            action="file_duplicate_skipped",
                            resource_type="file_checksum",
                            resource_id=channel.channel_name,
                            details={"filename": file_path.name},
                        )
                        await session.commit()

                    except Exception as e:
                        errors += 1
                        log.error(
                            "crawler_file_error",
                            filename=file_path.name,
                            channel=channel.channel_name,
                            error_type=type(e).__name__,
                            error_message=str(e),
                        )
                        await session.rollback()

    asyncio.run(run())

    result = {
        "status": "completed",
        "processed": processed,
        "skipped_duplicates": skipped,
        "errors": errors,
    }
    log.info("crawler_scan_completed", **result, function="scan_omv_storage")
    return result
