"""
app/repositories/channel_repo.py
Repository untuk channels dan channel_credentials.
Hanya query DB — tidak ada business logic di sini.
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.channel import Channel, ChannelCredential
from app.models.system import SystemAuditLog


class ChannelRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, channel_id: int) -> Channel | None:
        result = await self._session.execute(
            select(Channel)
            .options(selectinload(Channel.credential))
            .where(Channel.id == channel_id, Channel.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, channel_name: str) -> Channel | None:
        result = await self._session.execute(
            select(Channel).where(
                Channel.channel_name == channel_name,
                Channel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[Channel]:
        result = await self._session.execute(
            select(Channel)
            .options(selectinload(Channel.credential))
            .where(Channel.is_active.is_(True), Channel.deleted_at.is_(None))
            .order_by(Channel.channel_name)
        )
        return list(result.scalars().all())

    async def create(self, channel: Channel) -> Channel:
        self._session.add(channel)
        await self._session.flush()
        await self._session.refresh(channel)
        return channel

    async def update_trust_level(self, channel_id: int, trust_level: str) -> None:
        await self._session.execute(
            update(Channel)
            .where(Channel.id == channel_id)
            .values(trust_level=trust_level)
        )

    async def set_active(self, channel_id: int, is_active: bool) -> None:
        await self._session.execute(
            update(Channel)
            .where(Channel.id == channel_id)
            .values(is_active=is_active)
        )

    # ── Channel Credentials ──────────────────────────────────────

    async def get_credential(self, channel_id: int) -> ChannelCredential | None:
        result = await self._session.execute(
            select(ChannelCredential).where(
                ChannelCredential.channel_id == channel_id,
                ChannelCredential.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_credential(self, credential: ChannelCredential) -> ChannelCredential:
        """Insert or update credential. Setiap akses di-log ke audit log."""
        existing = await self.get_credential(credential.channel_id)
        if existing:
            existing.encrypted_client_id = credential.encrypted_client_id
            existing.encrypted_client_secret = credential.encrypted_client_secret
            existing.encrypted_refresh_token = credential.encrypted_refresh_token
            existing.encrypted_data_key = credential.encrypted_data_key
            existing.key_version = credential.key_version
            existing.auth_status = credential.auth_status
            await self._session.flush()
            return existing
        else:
            self._session.add(credential)
            await self._session.flush()
            await self._session.refresh(credential)
            return credential

    async def set_auth_status(self, channel_id: int, status: str) -> None:
        await self._session.execute(
            update(ChannelCredential)
            .where(ChannelCredential.channel_id == channel_id)
            .values(auth_status=status)
        )

    # ── Audit Log ────────────────────────────────────────────────

    async def write_audit_log(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Immutable audit log — tidak ada UPDATE/DELETE (RULE-004)."""
        log_entry = SystemAuditLog(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
        self._session.add(log_entry)
        await self._session.flush()
