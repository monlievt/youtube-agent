"""
app/api/routes/queue.py
Queue management API — monitor, override metadata, approve/reject, re-queue.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.api.dependencies import CurrentUser, DBSession
from app.core.logging import get_logger
from app.models.history import MetadataHistory
from app.repositories.queue_repo import QueueRepository
from app.schemas.queue import MetadataOverride, QueueItemResponse, RequeueRequest

log = get_logger(__name__)
router = APIRouter(prefix="/api/queue", tags=["Queue"])


@router.get("", response_model=list[QueueItemResponse])
async def list_queue(
    db: DBSession,
    user: CurrentUser,
    channel_id: int | None = None,
    status: str | None = None,
) -> list:
    repo = QueueRepository(db)
    if channel_id:
        return await repo.get_by_channel(channel_id, status=status)
    return await repo.get_all_by_status(status or "PENDING")


@router.get("/{queue_id}", response_model=QueueItemResponse)
async def get_queue_item(queue_id: int, db: DBSession, user: CurrentUser):
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")
    return item


@router.post("/{queue_id}/approve")
async def approve_queue_item(queue_id: int, db: DBSession, user: CurrentUser) -> dict:
    """Approve video AWAITING_APPROVAL → SCHEDULED."""
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    if item.status != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail=f"Item harus dalam status AWAITING_APPROVAL, bukan {item.status}"
        )

    await repo.transition_status(
        item, "SCHEDULED",
        reason="Human approved via dashboard",
        actor=f"human:{user}",
    )

    log.info(
        "queue_item_approved",
        queue_id=queue_id,
        actor=user,
        function="approve_queue_item",
    )
    return {"status": "approved", "queue_id": queue_id, "new_status": "SCHEDULED"}


@router.post("/{queue_id}/reject")
async def reject_queue_item(queue_id: int, db: DBSession, user: CurrentUser) -> dict:
    """Reject dan regenerate metadata."""
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    await repo.transition_status(
        item, "PENDING",
        reason="Human rejected — will regenerate metadata",
        actor=f"human:{user}",
    )

    log.info("queue_item_rejected", queue_id=queue_id, actor=user)
    return {"status": "rejected", "queue_id": queue_id, "new_status": "PENDING"}


@router.patch("/{queue_id}/metadata")
async def override_metadata(
    queue_id: int,
    data: MetadataOverride,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Human override judul dan deskripsi. Log ke metadata_history."""
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    old_title = item.title_final
    old_description = item.description_final

    item.title_final = data.title
    item.description_final = data.description
    item.is_human_override = True

    # Log perubahan
    for field_name, old_val, new_val in [
        ("title", old_title, data.title),
        ("description", old_description, data.description),
    ]:
        await repo.write_metadata_history(
            MetadataHistory(
                queue_id=queue_id,
                field_name=field_name,
                old_value=old_val,
                new_value=new_val[:500] if new_val else None,
                changed_by="HUMAN",
                change_reason=f"Dashboard override by {user}",
            )
        )

    log.info(
        "metadata_overridden",
        queue_id=queue_id,
        actor=user,
        function="override_metadata",
    )
    return {"status": "updated", "queue_id": queue_id}


@router.post("/{queue_id}/requeue")
async def requeue_failed(
    queue_id: int,
    data: RequeueRequest,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """
    Re-queue dari FAILED_PERMANENT — buat record BARU.
    Sesuai blueprint: tidak reset record lama, buat entri baru.
    """
    from app.models.queue import UploadQueue

    repo = QueueRepository(db)
    original = await repo.get_by_id(queue_id)
    if not original:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    if original.status not in ("FAILED_PERMANENT", "THUMBNAIL_FAILED"):
        raise HTTPException(
            status_code=400,
            detail=f"Hanya FAILED_PERMANENT atau THUMBNAIL_FAILED yang bisa di-requeue"
        )

    # Buat record baru
    new_item = UploadQueue(
        channel_id=original.channel_id,
        file_checksum_id=original.file_checksum_id,
        staging_path=original.staging_path,
        thumbnail_path=original.thumbnail_path,
        title_final=original.title_final,
        description_final=original.description_final,
        is_human_override=original.is_human_override,
        status="PENDING",
    )
    new_item = await repo.create(new_item)

    # Referensikan ID lama di history
    from app.models.history import MetadataHistory
    await repo.write_metadata_history(
        MetadataHistory(
            queue_id=new_item.id,
            field_name="status",
            old_value=None,
            new_value=f"Re-queued from original queue_id={queue_id}: {data.reason}",
            changed_by="HUMAN",
            change_reason=data.reason,
        )
    )

    log.info(
        "queue_requeued",
        original_queue_id=queue_id,
        new_queue_id=new_item.id,
        actor=user,
        function="requeue_failed",
    )
    return {
        "status": "requeued",
        "original_queue_id": queue_id,
        "new_queue_id": new_item.id,
    }
