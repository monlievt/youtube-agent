"""
app/services/credential_service.py
Service untuk manajemen OAuth credentials dengan dukungan Envelope Encryption.
Setiap akses credential di-log ke system_audit_log (RULE-005).
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt, encrypt, generate_data_key
from app.core.exceptions import InfrastructureError, TokenRevokedError
from app.core.logging import get_logger
from app.models.channel import Channel, ChannelCredential
from app.repositories.channel_repo import ChannelRepository

log = get_logger(__name__)


class CredentialService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = ChannelRepository(session)

    async def save_credentials(
        self,
        channel_id: int,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        actor: str = "SYSTEM",
        ip_address: str | None = None,
    ) -> ChannelCredential:
        """
        Enkripsi dan simpan credentials dengan Envelope Encryption.
        1. Generate data key baru acak (plaintext & terenkripsi oleh Master Key).
        2. Enkripsi credentials menggunakan plaintext data key.
        3. Simpan credentials dan encrypted_data_key ke DB.
        RULE-005: Tidak ada plaintext secret di kode, log, atau DB.
        """
        # Generate new random data key (envelope encryption)
        raw_data_key, enc_data_key = generate_data_key()

        encrypted_cred = ChannelCredential(
            channel_id=channel_id,
            encrypted_client_id=encrypt(client_id, raw_data_key),
            encrypted_client_secret=encrypt(client_secret, raw_data_key),
            encrypted_refresh_token=encrypt(refresh_token, raw_data_key),
            encrypted_data_key=enc_data_key,
            key_version=1,
            auth_status="VALID",
        )

        result = await self._repo.upsert_credential(encrypted_cred)

        # Log setiap penyimpanan credential ke audit log
        await self._repo.write_audit_log(
            actor=actor,
            action="credential_saved",
            resource_type="channel_credential",
            resource_id=str(channel_id),
            details={"channel_id": channel_id},
            ip_address=ip_address,
        )

        log.info(
            "credential_saved",
            channel_id=channel_id,
            actor=actor,
            function="save_credentials",
        )
        return result

    async def get_decrypted_credentials(
        self,
        channel_id: int,
        actor: str = "SYSTEM",
    ) -> tuple[str, str, str]:
        """
        Return (client_id, client_secret, refresh_token) dalam plaintext.
        Mendukung transisi: Jika record lama belum memiliki data key, 
        dekripsi dengan Master Key lalu auto-upgrade ke Envelope Encryption.
        WAJIB log setiap akses (RULE-005).
        """
        cred = await self._repo.get_credential(channel_id)
        if not cred:
            raise InfrastructureError(
                f"Tidak ada credential untuk channel_id={channel_id}"
            )

        if cred.auth_status == "REVOKED":
            raise TokenRevokedError(
                f"Token channel {channel_id} sudah di-revoke. Re-auth diperlukan."
            )

        # Log setiap akses credential (RULE-005)
        await self._repo.write_audit_log(
            actor=actor,
            action="credential_accessed",
            resource_type="channel_credential",
            resource_id=str(channel_id),
            details={"channel_id": channel_id, "auth_status": cred.auth_status},
        )

        # Cek apakah record menggunakan envelope encryption baru
        if cred.encrypted_data_key:
            # Dekripsi data key menggunakan Master Key
            raw_data_key = decrypt(cred.encrypted_data_key).encode()
            
            # Dekripsi credential menggunakan data key
            client_id = decrypt(cred.encrypted_client_id, raw_data_key)
            client_secret = decrypt(cred.encrypted_client_secret, raw_data_key)
            refresh_token = decrypt(cred.encrypted_refresh_token, raw_data_key)
        else:
            # Kredensial lama (Tier 1): Dekripsi dengan Master Key langsung
            client_id = decrypt(cred.encrypted_client_id)
            client_secret = decrypt(cred.encrypted_client_secret)
            refresh_token = decrypt(cred.encrypted_refresh_token)

            # Auto-upgrade ke Envelope Encryption
            log.info("credential_auto_upgrading_to_envelope", channel_id=channel_id)
            raw_data_key, enc_data_key = generate_data_key()
            
            cred.encrypted_client_id = encrypt(client_id, raw_data_key)
            cred.encrypted_client_secret = encrypt(client_secret, raw_data_key)
            cred.encrypted_refresh_token = encrypt(refresh_token, raw_data_key)
            cred.encrypted_data_key = enc_key = enc_data_key
            cred.key_version = 1
            await self._session.flush()

        return client_id, client_secret, refresh_token

    async def rotate_channel_key(
        self,
        channel_id: int,
        actor: str = "SYSTEM",
        ip_address: str | None = None,
    ) -> None:
        """
        Rotasi data key untuk channel tertentu.
        1. Ambil kredensial lama, dekripsi.
        2. Generate data key baru.
        3. Enkripsi ulang kredensial dengan data key baru.
        4. Update database (increment key_version).
        """
        cred = await self._repo.get_credential(channel_id)
        if not cred:
            raise InfrastructureError(
                f"Tidak ada credential untuk channel_id={channel_id}"
            )

        # Dekripsi credentials yang ada saat ini
        client_id, client_secret, refresh_token = await self.get_decrypted_credentials(
            channel_id, actor=actor
        )

        # Generate data key baru
        raw_data_key, enc_data_key = generate_data_key()

        # Enkripsi ulang menggunakan data key baru
        cred.encrypted_client_id = encrypt(client_id, raw_data_key)
        cred.encrypted_client_secret = encrypt(client_secret, raw_data_key)
        cred.encrypted_refresh_token = encrypt(refresh_token, raw_data_key)
        cred.encrypted_data_key = enc_data_key
        cred.key_version += 1

        await self._session.flush()

        # Log ke audit trail
        await self._repo.write_audit_log(
            actor=actor,
            action="credential_key_rotated",
            resource_type="channel_credential",
            resource_id=str(channel_id),
            details={"channel_id": channel_id, "new_version": cred.key_version},
            ip_address=ip_address,
        )

        log.info(
            "credential_key_rotated",
            channel_id=channel_id,
            new_version=cred.key_version,
            actor=actor,
        )

    async def handle_token_revocation(self, channel_id: int) -> None:
        """
        Tangani invalid_grant dari YouTube API.
        Pause channel dan log ke audit trail.
        """
        await self._repo.set_auth_status(channel_id, "REVOKED")
        await self._repo.set_active(channel_id, False)

        await self._repo.write_audit_log(
            actor="SYSTEM",
            action="token_revoked",
            resource_type="channel",
            resource_id=str(channel_id),
            details={"reason": "invalid_grant dari YouTube API"},
        )

        log.warning(
            "token_revoked_channel_paused",
            channel_id=channel_id,
            function="handle_token_revocation",
        )

    async def update_last_refreshed(self, channel_id: int) -> None:
        """Update timestamp terakhir kali token berhasil di-refresh."""
        cred = await self._repo.get_credential(channel_id)
        if cred:
            cred.last_refreshed = datetime.utcnow()
            await self._session.flush()
