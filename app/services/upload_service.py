"""
app/services/upload_service.py
Upload service — orkestrasi alur upload atomik sesuai blueprint.
PENDING → METADATA_READY → SCHEDULED → UPLOADING → PRIVATE_UPLOADED
→ THUMBNAIL_ATTACHED → SCHEDULED_PUBLIC → DONE
"""
import hashlib
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    DuplicateFileError,
    InfrastructureError,
    QuotaExhaustedError,
    TokenRevokedError,
)
from app.core.logging import get_logger
from app.gateways.youtube_gateway import YouTubeGateway
from app.models.queue import UploadAttempt, UploadQueue
from app.models.system import GcpQuotaTracker
from app.repositories.channel_repo import ChannelRepository
from app.repositories.config_repo import ConfigRepository
from app.repositories.queue_repo import QueueRepository
from app.models.file import FileChecksum
from app.services.credential_service import CredentialService

log = get_logger(__name__)
settings = get_settings()

# Upload menggunakan 1650 quota units per video (sesuai blueprint)
UPLOAD_QUOTA_UNITS = 1650


class UploadService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._queue_repo = QueueRepository(session)
        self._channel_repo = ChannelRepository(session)
        self._config_repo = ConfigRepository(session)
        self._credential_service = CredentialService(session)

    async def ingest_file(
        self,
        channel_id: int,
        nfs_file_path: str,
    ) -> UploadQueue:
        """
        Ingest file baru dari NFS ke staging dan queue.
        Sesuai blueprint Tahap 1: Copy NFS → Staging → Verify SHA256 → INSERT queue.
        """
        filename = os.path.basename(nfs_file_path)

        # Hitung SHA-256
        sha256 = self._calculate_sha256(nfs_file_path)
        file_size = os.path.getsize(nfs_file_path)

        # Cek duplikat
        existing = await self._queue_repo.get_checksum(channel_id, sha256)
        if existing:
            log.info(
                "file_duplicate_skipped",
                channel_id=channel_id,
                sha256=sha256[:8],
                filename=filename,
                function="ingest_file",
            )
            raise DuplicateFileError(
                f"File {filename} sudah ada di queue (sha256: {sha256[:16]}...)"
            )

        # Copy ke staging
        channel = await self._channel_repo.get_by_id(channel_id)
        if not channel:
            raise InfrastructureError(f"Channel {channel_id} tidak ditemukan")

        staging_dir = Path(settings.staging_path) / channel.channel_name
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = str(staging_dir / filename)

        shutil.copy2(nfs_file_path, staging_path)

        # Verify SHA-256 setelah copy
        staging_sha256 = self._calculate_sha256(staging_path)
        if staging_sha256 != sha256:
            os.unlink(staging_path)
            raise InfrastructureError(
                f"SHA-256 mismatch setelah copy ke staging. "
                f"Expected: {sha256}, Got: {staging_sha256}"
            )

        # Simpan checksum
        checksum = FileChecksum(
            channel_id=channel_id,
            sha256=sha256,
            filename=filename,
            file_size=file_size,
        )
        checksum = await self._queue_repo.create_checksum(checksum)

        # Insert ke queue
        queue_item = UploadQueue(
            channel_id=channel_id,
            file_checksum_id=checksum.id,
            staging_path=staging_path,
            status="PENDING",
        )
        queue_item = await self._queue_repo.create(queue_item)

        await self._queue_repo.transition_status(
            queue_item, "PENDING", reason="File ingested from NFS", actor="CRAWLER"
        )

        log.info(
            "file_ingested",
            channel_id=channel_id,
            queue_id=queue_item.id,
            sha256=sha256[:8],
            filename=filename,
            staging_path=staging_path,
            function="ingest_file",
        )
        return queue_item

    async def execute_upload(self, queue_item: UploadQueue, worker_id: str) -> None:
        """
        Eksekusi upload atomik: VIDEO → THUMBNAIL → SCHEDULE → ARCHIVE.
        Sesuai blueprint Tahap 5.
        """
        channel_id = queue_item.channel_id

        # Cek quota
        await self._check_and_reserve_quota(queue_item.channel.gcp_project_id)

        # Get credentials
        try:
            client_id, client_secret, refresh_token = (
                await self._credential_service.get_decrypted_credentials(
                    channel_id, actor=f"worker:{worker_id}"
                )
            )
        except TokenRevokedError:
            await self._queue_repo.transition_status(
                queue_item, "NEEDS_REAUTH",
                reason="Token revoked saat eksekusi upload",
                actor=f"worker:{worker_id}",
            )
            raise

        yt = YouTubeGateway(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            channel_id=channel_id,
        )

        # Idempotency check: apakah video sudah pernah di-upload?
        existing_video_attempt = await self._queue_repo.get_successful_attempt(
            queue_item.id, "VIDEO"
        )

        if existing_video_attempt:
            log.info(
                "idempotency_video_already_uploaded",
                queue_id=queue_item.id,
                youtube_video_id=existing_video_attempt.youtube_video_id,
            )
            youtube_video_id = existing_video_attempt.youtube_video_id
        else:
            # Step 1: Upload video
            idempotency_key = str(uuid.uuid4())
            attempt = UploadAttempt(
                queue_id=queue_item.id,
                idempotency_key=idempotency_key,
                attempt_number=queue_item.retry_count + 1,
                attempt_type="VIDEO",
            )
            attempt = await self._queue_repo.create_attempt(attempt)

            await self._queue_repo.transition_status(
                queue_item, "UPLOADING", actor=f"worker:{worker_id}"
            )
            queue_item.locked_at = datetime.utcnow()
            queue_item.worker_id = worker_id
            await self._session.flush()

            tags = [tag.tag for tag in queue_item.tags]
            youtube_video_id = yt.upload_video(
                video_path=queue_item.staging_path,
                title=queue_item.title_final or "Untitled",
                description=queue_item.description_final or "",
                tags=tags,
            )

            attempt.youtube_video_id = youtube_video_id
            attempt.success = True
            attempt.completed_at = datetime.utcnow()
            queue_item.youtube_video_id = youtube_video_id
            await self._session.flush()

            await self._queue_repo.transition_status(
                queue_item, "PRIVATE_UPLOADED", actor=f"worker:{worker_id}"
            )

        # Step 2: Upload thumbnail
        existing_thumb_attempt = await self._queue_repo.get_successful_attempt(
            queue_item.id, "THUMBNAIL"
        )

        if not existing_thumb_attempt and queue_item.thumbnail_path:
            thumb_idempotency_key = str(uuid.uuid4())
            thumb_attempt = UploadAttempt(
                queue_id=queue_item.id,
                idempotency_key=thumb_idempotency_key,
                attempt_number=1,
                attempt_type="THUMBNAIL",
            )
            thumb_attempt = await self._queue_repo.create_attempt(thumb_attempt)

            try:
                yt.upload_thumbnail(youtube_video_id, queue_item.thumbnail_path)
                thumb_attempt.success = True
                thumb_attempt.completed_at = datetime.utcnow()
                await self._session.flush()
                await self._queue_repo.transition_status(
                    queue_item, "THUMBNAIL_ATTACHED", actor=f"worker:{worker_id}"
                )
            except Exception as e:
                log.warning(
                    "thumbnail_upload_failed",
                    queue_id=queue_item.id,
                    youtube_video_id=youtube_video_id,
                    error_message=str(e),
                )
                await self._queue_repo.transition_status(
                    queue_item, "THUMBNAIL_FAILED",
                    reason=str(e)[:200],
                    actor=f"worker:{worker_id}",
                )
                return  # Video tetap PRIVATE, bisa retry thumbnail manual

        # Step 3: Set schedule
        schedule_idempotency_key = str(uuid.uuid4())
        schedule_attempt = UploadAttempt(
            queue_id=queue_item.id,
            idempotency_key=schedule_idempotency_key,
            attempt_number=1,
            attempt_type="SCHEDULE",
        )
        schedule_attempt = await self._queue_repo.create_attempt(schedule_attempt)

        yt.set_scheduled(youtube_video_id, queue_item.scheduled_time)
        schedule_attempt.success = True
        schedule_attempt.completed_at = datetime.utcnow()
        await self._session.flush()

        await self._queue_repo.transition_status(
            queue_item, "SCHEDULED_PUBLIC", actor=f"worker:{worker_id}"
        )

        # Step 4: Archive dan cleanup
        await self._archive_file(queue_item)

        await self._queue_repo.transition_status(
            queue_item, "DONE", actor=f"worker:{worker_id}"
        )

        # Update quota
        await self._update_quota_used(queue_item.channel.gcp_project_id)

        log.info(
            "upload_completed",
            queue_id=queue_item.id,
            channel_id=channel_id,
            youtube_video_id=youtube_video_id,
            function="execute_upload",
        )

    async def _archive_file(self, queue_item: UploadQueue) -> None:
        """Copy staging ke archive NFS, verify SHA256, hapus staging."""
        from pathlib import Path

        channel = queue_item.channel
        staging_path = queue_item.staging_path
        filename = os.path.basename(staging_path)

        # Archive ke NAS dengan subfolder YYYY-MM
        month_dir = datetime.utcnow().strftime("%Y-%m")
        archive_dir = Path(settings.nfs_archive_path) / channel.channel_name / month_dir
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = str(archive_dir / filename)

        shutil.copy2(staging_path, archive_path)

        # Verify setelah copy
        original_sha256 = self._calculate_sha256(staging_path)
        archive_sha256 = self._calculate_sha256(archive_path)

        if original_sha256 != archive_sha256:
            raise InfrastructureError(
                f"SHA-256 mismatch setelah archive. "
                f"Staging: {original_sha256}, Archive: {archive_sha256}"
            )

        os.unlink(staging_path)

        log.info(
            "file_archived",
            queue_id=queue_item.id,
            staging_path=staging_path,
            archive_path=archive_path,
            function="_archive_file",
        )

    async def _check_and_reserve_quota(self, project_id: str) -> None:
        """SELECT FOR UPDATE pada gcp_quota_tracker."""
        from sqlalchemy import select
        from app.models.system import GcpQuotaTracker

        result = await self._session.execute(
            select(GcpQuotaTracker)
            .where(GcpQuotaTracker.project_id == project_id)
            .with_for_update()
        )
        tracker = result.scalar_one_or_none()
        if not tracker:
            raise InfrastructureError(f"GCP project '{project_id}' tidak ditemukan di quota tracker")

        if tracker.units_used_today + UPLOAD_QUOTA_UNITS > tracker.units_limit:
            raise QuotaExhaustedError(
                f"Quota habis untuk project {project_id}. "
                f"Used: {tracker.units_used_today}, Limit: {tracker.units_limit}"
            )

    async def _update_quota_used(self, project_id: str) -> None:
        from sqlalchemy import select, update
        from app.models.system import GcpQuotaTracker

        await self._session.execute(
            update(GcpQuotaTracker)
            .where(GcpQuotaTracker.project_id == project_id)
            .values(
                units_used_today=GcpQuotaTracker.units_used_today + UPLOAD_QUOTA_UNITS,
                version=GcpQuotaTracker.version + 1,
            )
        )

    @staticmethod
    def _calculate_sha256(file_path: str) -> str:
        """Hitung SHA-256 hash dari file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
