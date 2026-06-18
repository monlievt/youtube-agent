"""
app/repositories/config_repo.py
Repository untuk system_config — no magic numbers di kode.
Sesuai RULE-002: semua konfigurasi di system_config, tidak ada default tersembunyi.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.system import SystemConfig

log = get_logger(__name__)

# Default fallback values (hanya digunakan jika DB belum di-seed)
_DEFAULTS: dict[str, str] = {
    "max_retry_count": "3",
    "openrouter_timeout_sec": "30",
    "default_publish_hour_utc": "15",
    "min_ctr_threshold": "2.0",
    "h24_views_threshold": "100",
    "upload_timeout_minutes": "30",
    "disk_warning_percent": "80",
    "disk_halt_percent": "90",
    "circuit_breaker_errors": "5",
    "circuit_breaker_wait_sec": "300",
    "approval_timeout_days": "7",
    "openrouter_primary": "meta-llama/llama-3.3-70b-instruct:free",
    "openrouter_fallback": "mistralai/mistral-7b-instruct:free",
    "openrouter_last_resort": "google/gemma-2-9b-it:free",
}


class ConfigRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, key: str) -> SystemConfig | None:
        result = await self._session.execute(
            select(SystemConfig).where(SystemConfig.config_key == key)
        )
        return result.scalar_one_or_none()

    async def get_value(self, key: str) -> str:
        """Return raw string value. Raise jika tidak ada dan tidak ada default."""
        cfg = await self.get(key)
        if cfg is not None:
            return cfg.config_value
        if key in _DEFAULTS:
            log.warning("config_using_default", key=key, default=_DEFAULTS[key])
            return _DEFAULTS[key]
        raise KeyError(f"Config key '{key}' tidak ditemukan di DB dan tidak ada default")

    async def get_int(self, key: str) -> int:
        return int(await self.get_value(key))

    async def get_float(self, key: str) -> float:
        return float(await self.get_value(key))

    async def get_bool(self, key: str) -> bool:
        v = await self.get_value(key)
        return v.lower() in ("true", "1", "yes")

    async def set_value(self, key: str, value: str) -> None:
        cfg = await self.get(key)
        if cfg:
            cfg.config_value = value
        else:
            log.warning("config_key_not_found_in_db", key=key)
        await self._session.flush()
