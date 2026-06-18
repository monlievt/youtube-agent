"""
tests/integration/test_queue_repo.py
Integration tests untuk QueueRepository — membutuhkan DB connection.
Gunakan testcontainers untuk MySQL atau SQLite in-memory.
"""
import pytest
import pytest_asyncio

from app.models.channel import Channel
from app.models.file import FileChecksum
from app.models.queue import UploadQueue
from app.repositories.queue_repo import QueueRepository


@pytest_asyncio.fixture
async def channel(db_session):
    ch = Channel(channel_name="test_channel", genre="lofi", trust_level="NEW")
    db_session.add(ch)
    await db_session.flush()
    return ch


@pytest_asyncio.fixture
async def checksum(db_session, channel):
    cs = FileChecksum(
        channel_id=channel.id,
        sha256="a" * 64,
        filename="test_video.mp4",
        file_size=1024,
    )
    db_session.add(cs)
    await db_session.flush()
    return cs


@pytest.mark.asyncio
async def test_create_and_get_queue_item(db_session, channel, checksum):
    repo = QueueRepository(db_session)

    item = UploadQueue(
        channel_id=channel.id,
        file_checksum_id=checksum.id,
        staging_path="/var/staging/test_channel/test_video.mp4",
        status="PENDING",
    )
    created = await repo.create(item)
    assert created.id is not None
    assert created.status == "PENDING"

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.status == "PENDING"


@pytest.mark.asyncio
async def test_transition_status_creates_history(db_session, channel, checksum):
    repo = QueueRepository(db_session)

    item = UploadQueue(
        channel_id=channel.id,
        file_checksum_id=checksum.id,
        staging_path="/var/staging/test_channel/test_video.mp4",
        status="PENDING",
    )
    item = await repo.create(item)

    await repo.transition_status(
        item, "METADATA_READY",
        reason="Test transition",
        actor="test",
    )

    assert item.status == "METADATA_READY"
    assert item.previous_status == "PENDING"


@pytest.mark.asyncio
async def test_checksum_duplicate_detection(db_session, channel, checksum):
    repo = QueueRepository(db_session)

    # Cari checksum yang sudah ada
    found = await repo.get_checksum(channel.id, "a" * 64)
    assert found is not None
    assert found.sha256 == "a" * 64

    # Cari yang tidak ada
    not_found = await repo.get_checksum(channel.id, "b" * 64)
    assert not_found is None
