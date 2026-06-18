"""
app/services/scheduler_service.py
Smart Prime Time Engine — pilih slot waktu upload terbaik.
Tier 1 (cold start): scatter ke 4 slot default.
Tier 2: gunakan timeslot_performance (ditambahkan setelah Tier 1 stabil 2 minggu).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.config_repo import ConfigRepository

log = get_logger(__name__)

# Slot default Tier 1 — scatter bergantian sesuai blueprint
# 07:00, 12:00, 20:00, 22:00 WIB = 00:00, 05:00, 13:00, 15:00 UTC
DEFAULT_SLOTS_UTC: list[int] = [0, 5, 13, 15]

_slot_counter: int = 0  # Counter round-robin


class SchedulerService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._config_repo = ConfigRepository(session)

    async def get_next_slot(self, channel_id: int) -> datetime:
        """
        Tentukan waktu publish berikutnya.
        Tier 1: round-robin ke 4 slot default.
        Tier 2: akan menggunakan timeslot_performance (TODO setelah Tier 1 stabil).
        """
        global _slot_counter

        # TODO Tier 2: Cek timeslot_performance untuk channel ini
        # Jika ada data dengan confidence >= 0.4, gunakan slot terbaik

        # Tier 1: Default scatter
        slot_hour_utc = DEFAULT_SLOTS_UTC[_slot_counter % len(DEFAULT_SLOTS_UTC)]
        _slot_counter += 1

        # Hitung datetime untuk slot berikutnya
        now = datetime.now(tz=timezone.utc)
        target = now.replace(
            hour=slot_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Jika slot hari ini sudah lewat, jadikan besok
        if target <= now:
            target += timedelta(days=1)

        # Pastikan minimal 1 jam dari sekarang
        if (target - now).total_seconds() < 3600:
            target += timedelta(days=1)

        log.info(
            "slot_assigned",
            channel_id=channel_id,
            scheduled_time=target.isoformat(),
            slot_hour_utc=slot_hour_utc,
            function="get_next_slot",
        )

        return target
