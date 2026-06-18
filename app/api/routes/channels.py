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
