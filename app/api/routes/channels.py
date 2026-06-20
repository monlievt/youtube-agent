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

