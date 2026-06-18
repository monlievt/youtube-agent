"""
tests/unit/test_encryption_envelope.py
Unit tests untuk Envelope Encryption dan Key Rotation pada CredentialService.
"""
import pytest
import pytest_asyncio

from app.core.encryption import encrypt, decrypt, generate_data_key
from app.models.channel import Channel
from app.services.credential_service import CredentialService


@pytest.mark.asyncio
async def test_envelope_encryption_core():
    # 1. Test generate_data_key
    raw_key, enc_key = generate_data_key()
    assert isinstance(raw_key, bytes)
    assert isinstance(enc_key, str)

    # 2. Test encrypt & decrypt with data key
    plaintext = "my_secret_token_123"
    ciphertext = encrypt(plaintext, raw_key)
    assert ciphertext != plaintext

    decrypted = decrypt(ciphertext, raw_key)
    assert decrypted == plaintext


@pytest.mark.asyncio
async def test_credential_service_envelope_flow(db_session):
    # Setup channel
    channel = Channel(
        channel_name="test_envelope_channel",
        genre="lofi",
        trust_level="NEW",
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()

    service = CredentialService(db_session)

    # Save credentials
    client_id = "test_client_id"
    client_secret = "test_client_secret"
    refresh_token = "test_refresh_token"

    cred = await service.save_credentials(
        channel_id=channel.id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        actor="TEST_USER",
    )

    assert cred.encrypted_data_key is not None
    assert cred.key_version == 1

    # Get credentials (decrypted)
    dec_client_id, dec_client_secret, dec_refresh_token = await service.get_decrypted_credentials(
        channel_id=channel.id,
        actor="TEST_USER",
    )

    assert dec_client_id == client_id
    assert dec_client_secret == client_secret
    assert dec_refresh_token == refresh_token


@pytest.mark.asyncio
async def test_key_rotation_flow(db_session):
    # Setup channel
    channel = Channel(
        channel_name="test_rotation_channel",
        genre="phonk",
        trust_level="NEW",
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()

    service = CredentialService(db_session)

    client_id = "rot_id"
    client_secret = "rot_secret"
    refresh_token = "rot_token"

    cred = await service.save_credentials(
        channel_id=channel.id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )

    old_encrypted_token = cred.encrypted_refresh_token
    old_data_key = cred.encrypted_data_key
    assert cred.key_version == 1

    # Run key rotation
    await service.rotate_channel_key(channel_id=channel.id, actor="TEST_ADMIN")

    # Refresh cred object
    await db_session.refresh(cred)

    assert cred.key_version == 2
    assert cred.encrypted_data_key != old_data_key
    assert cred.encrypted_refresh_token != old_encrypted_token

    # Verify decryption still works after rotation
    dec_client_id, dec_client_secret, dec_refresh_token = await service.get_decrypted_credentials(
        channel_id=channel.id,
        actor="TEST_USER",
    )

    assert dec_client_id == client_id
    assert dec_client_secret == client_secret
    assert dec_refresh_token == refresh_token
