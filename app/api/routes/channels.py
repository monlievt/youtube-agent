"""
app/api/routes/channels.py
Channel management API — CRUD, trust level, pause/resume.
"""
from fastapi import APIRouter, HTTPException

from app.api.dependencies import CurrentUser, DBSession
from app.core.logging import get_logger
from app.models.channel import Channel
from app.repositories.channel_repo import ChannelRepository
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelUpdate

log = get_logger(__name__)
router = APIRouter(prefix="/api/channels", tags=["Channels"])


@router.get("", response_model=list[ChannelResponse])
async def list_channels(db: DBSession, user: CurrentUser) -> list[Channel]:
    repo = ChannelRepository(db)
    return await repo.get_all_active()


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, db: DBSession, user: CurrentUser) -> Channel:
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")
    return channel


@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(
    data: ChannelCreate, db: DBSession, user: CurrentUser
) -> Channel:
    repo = ChannelRepository(db)

    # Cek nama duplikat
    existing = await repo.get_by_name(data.channel_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Channel '{data.channel_name}' sudah ada")

    channel = Channel(
        channel_name=data.channel_name,
        genre=data.genre,
        youtube_channel_id=data.youtube_channel_id,
        gcp_project_id=data.gcp_project_id,
        trust_level=data.trust_level,
    )
    channel = await repo.create(channel)

    await repo.write_audit_log(
        actor=user,
        action="channel_created",
        resource_type="channel",
        resource_id=str(channel.id),
        details={"channel_name": data.channel_name, "genre": data.genre},
    )

    log.info(
        "channel_created",
        channel_id=channel.id,
        channel_name=channel.channel_name,
        actor=user,
        function="create_channel",
    )
    return channel


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: int, data: ChannelUpdate, db: DBSession, user: CurrentUser
) -> Channel:
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    if data.trust_level is not None:
        await repo.update_trust_level(channel_id, data.trust_level)
        channel.trust_level = data.trust_level

    if data.is_active is not None:
        await repo.set_active(channel_id, data.is_active)
        channel.is_active = data.is_active

    if data.youtube_channel_id is not None:
        channel.youtube_channel_id = data.youtube_channel_id

    await repo.write_audit_log(
        actor=user,
        action="channel_updated",
        resource_type="channel",
        resource_id=str(channel_id),
        details=data.model_dump(exclude_none=True),
    )

    log.info("channel_updated", channel_id=channel_id, actor=user, function="update_channel")
    return channel


# ── Metadata Patterns Endpoints ───────────────────────────────
from pydantic import BaseModel, Field
from app.models.channel import MetadataPattern
from app.schemas.metadata import (
    MetadataPatternCreate,
    MetadataPatternResponse,
    MetadataPatternUpdate,
    MetadataOutput,
)

class PatternTestRequest(BaseModel):
    title_template: str
    description_template: str
    tags_template: str | None = None
    filename: str = "lofi_study_chill.mp4"


@router.get("/{channel_id}/patterns", response_model=list[MetadataPatternResponse])
async def list_patterns(channel_id: int, db: DBSession, user: CurrentUser) -> list[MetadataPattern]:
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")
    return await repo.get_patterns(channel_id)


@router.post("/{channel_id}/patterns", response_model=MetadataPatternResponse, status_code=201)
async def create_pattern(
    channel_id: int, data: MetadataPatternCreate, db: DBSession, user: CurrentUser
) -> MetadataPattern:
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    # Set patterns lain di channel ini menjadi nonaktif jika yang baru is_active
    if data.is_active:
        existing_patterns = await repo.get_patterns(channel_id)
        for p in existing_patterns:
            if p.is_active:
                p.is_active = False

    pattern = MetadataPattern(
        channel_id=channel_id,
        name=data.name,
        title_template=data.title_template,
        description_template=data.description_template,
        tags_template=data.tags_template,
        is_active=data.is_active,
    )
    pattern = await repo.create_pattern(pattern)
    await db.commit()
    return pattern


@router.patch("/patterns/{pattern_id}", response_model=MetadataPatternResponse)
async def update_pattern(
    pattern_id: int, data: MetadataPatternUpdate, db: DBSession, user: CurrentUser
) -> MetadataPattern:
    repo = ChannelRepository(db)
    pattern = await repo.get_pattern_by_id(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pola metadata tidak ditemukan")

    if data.name is not None:
        pattern.name = data.name
    if data.title_template is not None:
        pattern.title_template = data.title_template
    if data.description_template is not None:
        pattern.description_template = data.description_template
    if data.tags_template is not None:
        pattern.tags_template = data.tags_template

    if data.is_active is not None:
        if data.is_active and not pattern.is_active:
            existing_patterns = await repo.get_patterns(pattern.channel_id)
            for p in existing_patterns:
                if p.is_active and p.id != pattern_id:
                    p.is_active = False
        pattern.is_active = data.is_active

    await db.commit()
    await db.refresh(pattern)
    return pattern


@router.delete("/patterns/{pattern_id}", status_code=204)
async def delete_pattern(pattern_id: int, db: DBSession, user: CurrentUser) -> None:
    repo = ChannelRepository(db)
    pattern = await repo.get_pattern_by_id(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pola metadata tidak ditemukan")
    await repo.delete_pattern(pattern)
    await db.commit()


@router.post("/{channel_id}/test-pattern", response_model=MetadataOutput)
async def test_pattern(
    channel_id: int, data: PatternTestRequest, db: DBSession, user: CurrentUser
) -> MetadataOutput:
    from app.services.metadata_service import MetadataService
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    service = MetadataService(db)
    try:
        result = await service.generate_test_pattern(
            channel_id=channel_id,
            title_template=data.title_template,
            description_template=data.description_template,
            tags_template=data.tags_template,
            filename=data.filename,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Pattern Simulation gagal: {str(e)}")


@router.get("/{channel_id}/uploaded-videos")
async def list_uploaded_videos(channel_id: int, db: DBSession, user: CurrentUser):
    from app.repositories.queue_repo import QueueRepository
    from app.repositories.channel_repo import ChannelRepository
    import json
    
    # 1. Local database items
    queue_repo = QueueRepository(db)
    items = await queue_repo.get_by_channel(channel_id)
    uploaded = []
    local_video_ids = set()
    for item in items:
        if item.status in ("DONE", "SCHEDULED_PUBLIC", "PRIVATE_UPLOADED", "THUMBNAIL_ATTACHED"):
            if item.youtube_video_id:
                local_video_ids.add(item.youtube_video_id)
            uploaded.append({
                "id": item.id,
                "title": item.title_final or item.title_generated,
                "description": item.description_final or item.description_generated,
                "status": item.status,
                "youtube_video_id": item.youtube_video_id,
                "uploaded_at": item.updated_at.isoformat() if item.updated_at else None
            })
            
    # 2. Cached YouTube playlist items
    channel_repo = ChannelRepository(db)
    channel = await channel_repo.get_by_id(channel_id)
    if channel and channel.youtube_videos_cache:
        try:
            cached_videos = json.loads(channel.youtube_videos_cache)
            for cv in cached_videos:
                v_id = cv.get("youtube_video_id")
                # Avoid duplicate with local items
                if v_id and v_id not in local_video_ids:
                    uploaded.append({
                        "id": f"yt-{v_id}",
                        "title": cv.get("title"),
                        "description": cv.get("description"),
                        "status": "DONE",
                        "youtube_video_id": v_id,
                        "uploaded_at": cv.get("published_at")
                    })
        except Exception as e:
            log.error("load_cached_videos_failed", error=str(e))
            
    return uploaded


@router.post("/{channel_id}/sync")
async def sync_channel_data(channel_id: int, db: DBSession, user: CurrentUser):
    """Trigger background metadata & video sync task for a channel."""
    from app.workers.analytics_tasks import sync_channel_metadata_task
    
    repo = ChannelRepository(db)
    channel = await repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")
        
    if not channel.credential or channel.auth_status != "VALID":
        raise HTTPException(status_code=400, detail="OAuth belum terhubung untuk channel ini")
        
    # Jalankan background task
    sync_channel_metadata_task.delay(channel_id, actor=f"human:{user}")
    
    await repo.write_audit_log(
        actor=user,
        action="channel_sync_triggered",
        resource_type="channel",
        resource_id=str(channel_id),
        details={"channel_name": channel.channel_name},
    )
    
    return {"status": "sync_triggered", "channel_id": channel_id}


@router.get("/{channel_id}/pattern-analytics")
async def get_pattern_analytics(channel_id: int, db: DBSession, user: CurrentUser):
    from sqlalchemy import select
    from app.models.queue import UploadQueue
    from app.models.analytics import AnalyticsLog
    from app.repositories.queue_repo import QueueRepository

    repo = ChannelRepository(db)
    patterns = await repo.get_patterns(channel_id)
    result_data = []

    for pattern in patterns:
        q_result = await db.execute(
            select(UploadQueue.youtube_video_id)
            .where(UploadQueue.channel_id == channel_id, UploadQueue.pattern_id == pattern.id)
        )
        video_ids = [r[0] for r in q_result.all() if r[0]]

        if video_ids:
            views_sum = 0
            ctr_avg = 0.0
            likes_sum = 0
            count = 0
            for vid in video_ids:
                log_result = await db.execute(
                    select(AnalyticsLog)
                    .where(AnalyticsLog.youtube_video_id == vid)
                    .order_by(AnalyticsLog.pulled_at.desc())
                    .limit(1)
                )
                log_entry = log_result.scalar_one_or_none()
                if log_entry:
                    views_sum += log_entry.views
                    ctr_avg += log_entry.ctr_percentage
                    likes_sum += log_entry.likes
                    count += 1
            
            result_data.append({
                "pattern_id": pattern.id,
                "pattern_name": pattern.name,
                "views": views_sum,
                "likes": likes_sum,
                "ctr": round(ctr_avg / count, 2) if count > 0 else 0.0,
                "sample_count": len(video_ids)
            })
        else:
            result_data.append({
                "pattern_id": pattern.id,
                "pattern_name": pattern.name,
                "views": 0,
                "likes": 0,
                "ctr": 0.0,
                "sample_count": 0
            })

    return result_data


