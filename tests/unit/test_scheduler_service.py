"""
tests/unit/test_scheduler_service.py
Unit tests untuk SchedulerService — slot assignment.
"""
from datetime import datetime, timezone

import pytest

from app.services.scheduler_service import DEFAULT_SLOTS_UTC, SchedulerService


def test_default_slots_are_defined():
    assert len(DEFAULT_SLOTS_UTC) == 4
    assert all(0 <= h < 24 for h in DEFAULT_SLOTS_UTC)


@pytest.mark.asyncio
async def test_slot_in_future(db_session):
    """Slot yang di-assign selalu di masa depan (minimal 1 jam dari sekarang)."""
    service = SchedulerService(db_session)
    scheduled = await service.get_next_slot(channel_id=1)

    now = datetime.now(tz=timezone.utc)
    diff = (scheduled - now).total_seconds()
    assert diff >= 3600, f"Slot terlalu dekat: {diff:.0f} detik dari sekarang"


@pytest.mark.asyncio
async def test_slot_round_robin(db_session):
    """Setiap call menghasilkan slot yang berbeda (round-robin)."""
    service = SchedulerService(db_session)
    slots = [await service.get_next_slot(channel_id=1) for _ in range(4)]
    hours = [s.hour for s in slots]
    # Semua 4 slot default harus muncul dalam 4 call
    assert len(set(hours)) > 1, "Round-robin harus variasi slot"
