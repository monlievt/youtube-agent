"""
app/core/circuit_breaker.py
Circuit breaker sederhana per model/service.
State: CLOSED (normal) → OPEN (fail fast) → HALF_OPEN (coba lagi)
Threshold dan wait time dari system_config (default: 5 error → wait 300 detik).
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

from app.core.exceptions import CircuitBreakerOpenError
from app.core.logging import get_logger

log = get_logger(__name__)


class CBState(str, Enum):
    CLOSED = "CLOSED"      # Normal
    OPEN = "OPEN"          # Fail fast
    HALF_OPEN = "HALF_OPEN"  # Sedang di-test


@dataclass
class CircuitBreaker:
    """
    Circuit breaker per resource (misalnya per OpenRouter model).
    Thread-safe menggunakan Lock.
    """
    name: str
    error_threshold: int = 5
    wait_seconds: int = 300

    _state: CBState = field(default=CBState.CLOSED, init=False)
    _error_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def call(self) -> None:
        """
        Panggil sebelum memanggil resource.
        Raise CircuitBreakerOpenError jika state OPEN.
        """
        with self._lock:
            if self._state == CBState.OPEN:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.wait_seconds:
                    self._state = CBState.HALF_OPEN
                    log.info(
                        "circuit_breaker_half_open",
                        name=self.name,
                        elapsed_seconds=int(elapsed),
                    )
                else:
                    remaining = int(self.wait_seconds - elapsed)
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' OPEN. "
                        f"Tunggu {remaining} detik lagi.",
                        status_code=503,
                    )

    def record_success(self) -> None:
        """Catat sukses — reset ke CLOSED."""
        with self._lock:
            self._error_count = 0
            if self._state != CBState.CLOSED:
                log.info("circuit_breaker_closed", name=self.name)
            self._state = CBState.CLOSED

    def record_failure(self) -> None:
        """Catat failure — buka circuit jika threshold tercapai."""
        with self._lock:
            self._error_count += 1
            self._last_failure_time = time.time()

            if self._error_count >= self.error_threshold:
                self._state = CBState.OPEN
                log.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    error_count=self._error_count,
                    wait_seconds=self.wait_seconds,
                )

    @property
    def state(self) -> CBState:
        return self._state

    @property
    def error_count(self) -> int:
        return self._error_count


# Registry global — satu instance per named resource
_registry: dict[str, CircuitBreaker] = {}
_registry_lock = Lock()


def get_circuit_breaker(
    name: str,
    error_threshold: int = 5,
    wait_seconds: int = 300,
) -> CircuitBreaker:
    """
    Dapatkan atau buat circuit breaker berdasarkan nama.
    Threshold dan wait bisa di-override dari system_config.
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                error_threshold=error_threshold,
                wait_seconds=wait_seconds,
            )
        return _registry[name]
