"""
app/core/encryption.py
Fernet symmetric encryption & envelope encryption (Master Key -> Data Key -> Credential).
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import InfrastructureError
from app.core.logging import get_logger

log = get_logger(__name__)


def _get_master_key() -> bytes:
    """Ambil master key dari environment. TIDAK pernah dari DB atau kode."""
    key = os.environ.get("HERMES_MASTER_KEY")
    if not key:
        raise InfrastructureError(
            "HERMES_MASTER_KEY tidak ditemukan di environment. "
            "Generate dengan: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return key.encode()


def encrypt(plaintext: str, key: bytes | None = None) -> str:
    """
    Enkripsi string plaintext menggunakan Fernet.
    Jika key disediakan, gunakan key tersebut (Data Key).
    Jika tidak, gunakan Master Key dari environment.
    Return: ciphertext sebagai string (url-safe base64).
    """
    try:
        encryption_key = key if key is not None else _get_master_key()
        fernet = Fernet(encryption_key)
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    except Exception as e:
        log.error("encryption_failed", error_type=type(e).__name__, error_message=str(e))
        raise InfrastructureError(f"Enkripsi gagal: {e}") from e


def decrypt(ciphertext: str, key: bytes | None = None) -> str:
    """
    Dekripsi ciphertext Fernet ke plaintext.
    Jika key disediakan, gunakan key tersebut (Data Key).
    Jika tidak, gunakan Master Key dari environment.
    Raise InfrastructureError jika token invalid atau expired.
    """
    try:
        decryption_key = key if key is not None else _get_master_key()
        fernet = Fernet(decryption_key)
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken as e:
        log.error("decryption_failed_invalid_token", error_message=str(e))
        raise InfrastructureError("Token enkripsi tidak valid atau sudah expired") from e
    except Exception as e:
        log.error("decryption_failed", error_type=type(e).__name__, error_message=str(e))
        raise InfrastructureError(f"Dekripsi gagal: {e}") from e


def generate_key() -> str:
    """Generate Fernet key baru."""
    return Fernet.generate_key().decode()


def generate_data_key() -> tuple[bytes, str]:
    """
    Membangun data key baru (envelope encryption).
    1. Generate random key (plaintext data key).
    2. Enkripsi plaintext data key tersebut menggunakan Master Key.
    Return: (plaintext_data_key_bytes, encrypted_data_key_string)
    """
    raw_key = Fernet.generate_key()
    encrypted_key = encrypt(raw_key.decode())
    return raw_key, encrypted_key
