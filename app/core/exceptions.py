"""
app/core/exceptions.py
Custom exception hierarchy sesuai blueprint (Konvensi Kode).
"""


class HermesError(Exception):
    """Base exception untuk semua error Hermes."""
    pass


class DomainError(HermesError):
    """Business rule violation — logika domain dilanggar."""
    pass


class InfrastructureError(HermesError):
    """Error pada infrastruktur: DB, Redis, filesystem."""
    pass


class ExternalAPIError(HermesError):
    """Error dari external API: YouTube, OpenRouter."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class QuotaExhaustedError(ExternalAPIError):
    """YouTube API quota habis hari ini."""
    pass


class TokenRevokedError(ExternalAPIError):
    """OAuth token di-revoke — butuh re-auth."""
    pass


class CircuitBreakerOpenError(ExternalAPIError):
    """Circuit breaker open — terlalu banyak error."""
    pass


class NFSUnavailableError(InfrastructureError):
    """NFS mount tidak tersedia."""
    pass


class DuplicateFileError(DomainError):
    """File dengan SHA-256 yang sama sudah ada di queue."""
    pass


class InvalidStateTransitionError(DomainError):
    """Transisi status tidak valid sesuai state machine."""
    def __init__(self, from_state: str, to_state: str):
        super().__init__(
            f"Transisi tidak valid: {from_state} → {to_state}"
        )
        self.from_state = from_state
        self.to_state = to_state


class MetadataValidationError(DomainError):
    """Output AI tidak memenuhi validasi Pydantic."""
    pass
