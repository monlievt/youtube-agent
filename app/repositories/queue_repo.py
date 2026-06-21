"""
app/repositories/queue_repo.py
Repository untuk upload_queue — termasuk SELECT FOR UPDATE SKIP LOCKED.
"""
from datetime import datetime

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.file import FileChecksum
from app.models.history import MetadataHistory, UploadStateHistory
from app.models.queue import UploadAttempt, UploadQueue, VideoTag


class QueueRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, queue_id: int) -> UploadQueue | None:
        result = await self._session.execute(
            select(UploadQueue)
            .options(selectinload(UploadQueue.tags))
            .where(UploadQueue.id == queue_id, UploadQueue.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_channel(
        self, channel_id: int, status: str | None = None
    ) -> list[UploadQueue]:
        q = select(UploadQueue).options(selectinload(UploadQueue.tags)).where(
            UploadQueue.channel_id == channel_id,
            UploadQueue.deleted_at.is_(None),
        )
        if status:
            q = q.where(UploadQueue.status == status)
        result = await self._session.execute(q.order_by(UploadQueue.created_at.desc()))
        return list(result.scalars().all())

    async def get_all_by_status(self, status: str | None = None) -> list[UploadQueue]:
        q = select(UploadQueue).options(selectinload(UploadQueue.tags)).where(UploadQueue.deleted_at.is_(None))
        if status:
            q = q.where(UploadQueue.status == status)
        result = await self._session.execute(q.order_by(UploadQueue.created_at.desc()))
        return list(result.scalars().all())

    async def lock_next_pending(self) -> UploadQueue | None:
        """
        SELECT FOR UPDATE SKIP LOCKED — atomik, tidak ada race condition.
        Digunakan oleh metadata worker untuk ambil item PENDING.
        """
        result = await self._session.execute(
            select(UploadQueue)
            .options(selectinload(UploadQueue.channel))
            .where(
                UploadQueue.status == "PENDING",
                UploadQueue.deleted_at.is_(None),
            )
            .order_by(UploadQueue.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def lock_next_scheduled(self) -> UploadQueue | None:
        """
        Ambil item SCHEDULED yang waktunya sudah tiba.
        SELECT FOR UPDATE SKIP LOCKED.
        """
        result = await self._session.execute(
            select(UploadQueue)
            .options(selectinload(UploadQueue.channel))
            .where(
                UploadQueue.status == "SCHEDULED",
                UploadQueue.scheduled_time <= datetime.utcnow(),
                UploadQueue.deleted_at.is_(None),
            )
            .order_by(UploadQueue.scheduled_time)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def transition_status(
        self,
        queue_item: UploadQueue,
        new_status: str,
        reason: str | None = None,
        actor: str = "SYSTEM",
    ) -> None:
        """
        Transisi status dengan validasi dan audit trail otomatis.
        Setiap transisi WAJIB via fungsi ini (RULE-009).
        """
        old_status = queue_item.status
        queue_item.previous_status = old_status
        queue_item.status = new_status

        # Log ke upload_state_history
        state_log = UploadStateHistory(
            queue_id=queue_item.id,
            from_state=old_status,
            to_state=new_status,
            reason=reason,
            actor=actor,
        )
        self._session.add(state_log)
        await self._session.flush()

    async def create(self, queue_item: UploadQueue) -> UploadQueue:
        self._session.add(queue_item)
        await self._session.flush()
        await self._session.refresh(queue_item)
        return queue_item

    async def get_checksum(self, channel_id: int, sha256: str) -> FileChecksum | None:
        result = await self._session.execute(
            select(FileChecksum).where(
                FileChecksum.channel_id == channel_id,
                FileChecksum.sha256 == sha256,
            )
        )
        return result.scalar_one_or_none()

    async def create_checksum(self, checksum: FileChecksum) -> FileChecksum:
        self._session.add(checksum)
        await self._session.flush()
        await self._session.refresh(checksum)
        return checksum

    async def add_tags(self, tags: list[VideoTag]) -> None:
        for tag in tags:
            self._session.add(tag)
        await self._session.flush()

    async def write_metadata_history(self, entry: MetadataHistory) -> None:
        self._session.add(entry)
        await self._session.flush()

    async def create_attempt(self, attempt: UploadAttempt) -> UploadAttempt:
        self._session.add(attempt)
        await self._session.flush()
        await self._session.refresh(attempt)
        return attempt

    async def get_successful_attempt(
        self, queue_id: int, attempt_type: str
    ) -> UploadAttempt | None:
        """Cek idempotency — ada attempt sukses untuk type ini?"""
        result = await self._session.execute(
            select(UploadAttempt).where(
                UploadAttempt.queue_id == queue_id,
                UploadAttempt.attempt_type == attempt_type,
                UploadAttempt.success.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_stuck_uploading(self, timeout_minutes: int) -> list[UploadQueue]:
        """Cari item UPLOADING yang stuck lebih dari timeout_minutes."""
        result = await self._session.execute(
            text(
                "SELECT * FROM upload_queue "
                "WHERE status = 'UPLOADING' "
                "  AND locked_at < NOW() - INTERVAL :minutes MINUTE "
                "  AND deleted_at IS NULL"
            ).bindparams(minutes=timeout_minutes)
        )
        rows = result.mappings().all()
        return [UploadQueue(**dict(row)) for row in rows]

    async def get_pending_approval_expired(self, timeout_days: int) -> list[UploadQueue]:
        """Cari AWAITING_APPROVAL yang sudah lebih dari timeout_days."""
        result = await self._session.execute(
            text(
                "SELECT * FROM upload_queue "
                "WHERE status = 'AWAITING_APPROVAL' "
                "  AND created_at < NOW() - INTERVAL :days DAY "
                "  AND deleted_at IS NULL"
            ).bindparams(days=timeout_days)
        )
        rows = result.mappings().all()
        return [UploadQueue(**dict(row)) for row in rows]
