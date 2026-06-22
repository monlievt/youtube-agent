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
        return await repo.get_by_channel(channel_id, status=status if status else None)
    return await repo.get_all_by_status(status if status else None)


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
    item.category_id = data.category_id
    item.made_for_kids = data.made_for_kids
    item.is_altered_content = data.is_altered_content
    item.playlist_id = data.playlist_id

    # Simpan sebagai preset jika dicentang
    if data.save_as_preset:
        from app.repositories.channel_repo import ChannelRepository
        channel_repo = ChannelRepository(db)
        patterns = await channel_repo.get_patterns(item.channel_id)
        active_pattern = next((p for p in patterns if p.is_active), None)
        if active_pattern:
            active_pattern.category_id = data.category_id or "10"
            active_pattern.made_for_kids = data.made_for_kids
            active_pattern.is_altered_content = data.is_altered_content
            active_pattern.playlist_id = data.playlist_id
        elif patterns:
            patterns[0].category_id = data.category_id or "10"
            patterns[0].made_for_kids = data.made_for_kids
            patterns[0].is_altered_content = data.is_altered_content
            patterns[0].playlist_id = data.playlist_id
        else:
            from app.models.channel import MetadataPattern
            new_pattern = MetadataPattern(
                channel_id=item.channel_id,
                name="Default Preset",
                title_template="{title}",
                description_template="{description}",
                category_id=data.category_id or "10",
                made_for_kids=data.made_for_kids,
                is_altered_content=data.is_altered_content,
                playlist_id=data.playlist_id,
                is_active=True,
            )
            db.add(new_pattern)

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

    if original.status not in (
        "FAILED_PERMANENT",
        "THUMBNAIL_FAILED",
        "PAUSED_EXTERNAL",
        "PAUSED",
        "QUOTA_EXHAUSTED",
        "NEEDS_REAUTH",
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Hanya status gagal, tertunda (paused), atau quota/auth exhausted yang bisa di-requeue (status saat ini: {original.status})"
        )

    # Reset kolom-kolom terkait eksekusi sebelumnya
    original.error_message = None
    original.retry_count = 0
    original.next_retry_at = None
    original.locked_at = None
    original.worker_id = None
    original.youtube_video_id = None

    # Transisi status ke PENDING
    await repo.transition_status(
        original, "PENDING",
        reason=f"Re-queued: {data.reason}",
        actor=f"human:{user}",
    )

    # Referensikan aksi requeue di metadata history
    from app.models.history import MetadataHistory
    await repo.write_metadata_history(
        MetadataHistory(
            queue_id=original.id,
            field_name="status",
            old_value=original.previous_status,
            new_value=f"Re-queued back to PENDING: {data.reason}",
            changed_by="HUMAN",
            change_reason=data.reason,
        )
    )

    log.info(
        "queue_requeued",
        queue_id=queue_id,
        actor=user,
        function="requeue_failed",
    )
    return {
        "status": "requeued",
        "original_queue_id": queue_id,
        "new_queue_id": original.id,
    }


# ── Telegram Bot Webhook Endpoint ─────────────────────────────
from fastapi import Request
import httpx

@router.post("/telegram-webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    """
    Webhook handler untuk menangkap klik tombol persetujuan dari Telegram Bot.
    """
    from app.core.database import AsyncSessionLocal
    try:
        data = await request.json()
        log.info("telegram_webhook_payload_received", data=data)
        
        callback_query = data.get("callback_query")
        if not callback_query:
            return {"status": "ignored"}

        callback_data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        message_id = message.get("message_id")
        chat_id = message.get("chat", {}).get("id")
        callback_query_id = callback_query.get("id")

        if not callback_data or ":" not in callback_data:
            return {"status": "ignored"}

        action, queue_id_str = callback_data.split(":")
        queue_id = int(queue_id_str)

        async with AsyncSessionLocal() as db:
            repo = QueueRepository(db)
            item = await repo.get_by_id(queue_id)

            if not item:
                await answer_callback(callback_query_id, "Item antrean tidak ditemukan.")
                return {"status": "error", "detail": "not found"}

            new_text = ""
            if action == "approve_upload":
                if item.status != "AWAITING_APPROVAL":
                    await answer_callback(callback_query_id, f"Gagal: status saat ini {item.status}")
                    return {"status": "error"}

                await repo.transition_status(
                    item, "SCHEDULED",
                    reason="Disetujui via Telegram Bot",
                    actor="telegram_bot",
                )
                await db.commit()
                filename = item.staging_path.split("/")[-1] if item.staging_path else "video"
                new_text = f"✅ Video #{queue_id} (<code>{filename}</code>) telah <b>DISETUJUI</b> dan dijadwalkan publik."

            elif action == "reject_upload":
                await repo.transition_status(
                    item, "PENDING",
                    reason="Ditolak via Telegram Bot (metadata akan digenerate ulang)",
                    actor="telegram_bot",
                )
                await db.commit()
                new_text = f"❌ Video #{queue_id} telah <b>DITOLAK</b>. Metadata akan digenerate ulang oleh AI."

            elif action == "approve_thumb":
                new_text = f"✅ Gambar Mini (Thumbnail) untuk video #{queue_id} telah <b>DISETUJUI</b>."

            elif action == "recreate_thumb":
                await repo.transition_status(
                    item, "THUMBNAIL_FAILED",
                    reason="Thumbnail ditolak via Telegram, minta generate ulang",
                    actor="telegram_bot",
                )
                await db.commit()
                new_text = f"🔄 Thumbnail untuk video #{queue_id} <b>DITOLAK</b>. Diminta untuk generate ulang."

            if new_text:
                await edit_telegram_message(chat_id, message_id, new_text)
                await answer_callback(callback_query_id, "Berhasil diproses!")

        return {"status": "processed"}
    except Exception as e:
        log.error("telegram_webhook_error", error=str(e))
        return {"status": "error", "message": str(e)}


async def answer_callback(callback_query_id: str, text: str):
    """Beri respons pop-up/toast di aplikasi Telegram."""
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=5)
    except Exception:
        pass


async def edit_telegram_message(chat_id: int, message_id: int, text: str):
    """Edit pesan asli di Telegram untuk menghilangkan tombol."""
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": []}
            }, timeout=5)
    except Exception:
        pass


@router.delete("/{queue_id}")
async def delete_queue_item(queue_id: int, db: DBSession, user: CurrentUser) -> dict:
    """Soft delete queue item dari database dan hapus file fisik dari disk."""
    import os
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    # Hapus file video fisik
    if item.staging_path and os.path.exists(item.staging_path):
        try:
            os.unlink(item.staging_path)
            log.info("staging_file_deleted", path=item.staging_path)
        except Exception as e:
            log.warning("failed_to_delete_staging_file", path=item.staging_path, error=str(e))

    # Hapus file thumbnail fisik
    if item.thumbnail_path and os.path.exists(item.thumbnail_path):
        try:
            os.unlink(item.thumbnail_path)
            log.info("thumbnail_file_deleted", path=item.thumbnail_path)
        except Exception as e:
            log.warning("failed_to_delete_thumbnail_file", path=item.thumbnail_path, error=str(e))

    # Soft delete di DB
    item.deleted_at = datetime.utcnow()
    await db.commit()

    log.info("queue_item_deleted", queue_id=queue_id, actor=user)
    return {"status": "deleted", "queue_id": queue_id}


from app.schemas.queue import ReorderRequest

@router.post("/{queue_id}/reorder")
async def reorder_queue_item(
    queue_id: int,
    data: ReorderRequest,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Ubah urutan/prioritas item queue (up/down)."""
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    if data.direction == "up":
        item.priority += 1
    elif data.direction == "down":
        item.priority -= 1
    else:
        raise HTTPException(status_code=400, detail="Direction tidak valid. Harus 'up' atau 'down'.")

    await db.commit()
    log.info("queue_item_reordered", queue_id=queue_id, new_priority=item.priority, actor=user)
    return {"status": "reordered", "queue_id": queue_id, "new_priority": item.priority}


@router.post("/{queue_id}/generate-ai-thumbnail")
async def generate_ai_thumbnail(
    queue_id: int,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Generate thumbnail menggunakan API gratis dari Pollinations AI."""
    import httpx
    import urllib.parse
    from app.core.config import get_settings
    from pathlib import Path

    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item tidak ditemukan")

    settings = get_settings()
    channel = item.channel
    genre = channel.genre if channel else "lofi"
    title = item.title_final or item.title_generated or "chill music"

    # Construct prompt untuk Pollinations AI
    prompt = f"beautiful {genre} music album cover, aesthetic illustration, cozy mood, high resolution, 4k, no text, inspired by {title}"
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&nologo=true&private=true"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(url)
            if res.status_code != 200:
                raise HTTPException(status_code=502, detail="Gagal menghubungi API Pollinations AI")

            # Simpan file ke folder thumbnails
            output_dir = Path(settings.nfs_thumbnails_path) / (channel.channel_name if channel else "default")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"ai_{queue_id}.jpg"

            with open(output_path, "wb") as f:
                f.write(res.content)

            item.thumbnail_path = str(output_path)
            await db.commit()

            log.info("ai_thumbnail_generated", queue_id=queue_id, path=str(output_path))
            return {"status": "success", "thumbnail_path": f"/api/queue/{queue_id}/thumbnail?t={datetime.utcnow().timestamp()}"}

    except Exception as e:
        log.error("ai_thumbnail_generation_failed", queue_id=queue_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Gagal generate thumbnail: {str(e)}")


from fastapi.responses import FileResponse

@router.get("/{queue_id}/thumbnail")
async def get_queue_thumbnail(queue_id: int, db: DBSession, user: CurrentUser):
    """Serve file thumbnail fisik untuk pratinjau di dashboard."""
    repo = QueueRepository(db)
    item = await repo.get_by_id(queue_id)
    if not item or not item.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail tidak ditemukan untuk item ini")

    import os
    if not os.path.exists(item.thumbnail_path):
        raise HTTPException(status_code=404, detail="File thumbnail fisik tidak ditemukan di server")

    return FileResponse(item.thumbnail_path)

