"""
app/gateways/openrouter_gateway.py
OpenRouter API adapter dengan fallback chain dan circuit breaker.
Sesuai blueprint: Primary → Fallback → Last Resort → PAUSED_EXTERNAL
"""
import json
import time

import httpx

from app.core.circuit_breaker import get_circuit_breaker
from app.core.config import get_settings
from app.core.exceptions import CircuitBreakerOpenError, ExternalAPIError
from app.core.logging import get_logger

log = get_logger(__name__)

settings = get_settings()

DEFAULT_MODEL_CHAIN = [
    "google/gemini-3.5-flash",                  # Paid primary (fast, robust & extremely cheap)
    "meta-llama/llama-3.3-70b-instruct:free",   # Primary free fallback
    "mistralai/mistral-7b-instruct:free",         # Fallback
    "google/gemma-2-9b-it:free",                  # Last resort
]

# Threshold untuk switch model: 3x error 429/5xx dalam 60 detik
_CONSECUTIVE_ERROR_THRESHOLD = 3
_model_error_counts: dict[str, int] = {}
_model_error_timestamps: dict[str, list[float]] = {}


class OpenRouterGateway:
    """
    Adapter untuk OpenRouter API.
    Satu key, banyak model, fallback chain eksplisit.
    """

    def __init__(self, model_chain: list[str] | None = None, timeout_seconds: int = 30):
        self._model_chain = model_chain or DEFAULT_MODEL_CHAIN
        self._timeout = timeout_seconds
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._api_key = settings.openrouter_api_key

    def generate_text(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        """
        Generate text dengan fallback chain otomatis.
        Return: (generated_text, model_yang_digunakan)
        Raise ExternalAPIError jika semua model gagal.
        """
        last_error: Exception | None = None

        for model in self._model_chain:
            cb = get_circuit_breaker(f"openrouter:{model}")

            try:
                cb.call()  # Cek apakah circuit breaker open
            except CircuitBreakerOpenError:
                log.warning(
                    "openrouter_circuit_open_skip",
                    model=model,
                    function="generate_text",
                )
                continue

            try:
                result = self._call_api(model=model, prompt=prompt, system_prompt=system_prompt)
                cb.record_success()
                log.info(
                    "openrouter_generate_success",
                    model=model,
                    prompt_length=len(prompt),
                )
                return result, model

            except ExternalAPIError as e:
                cb.record_failure()
                last_error = e
                log.warning(
                    "openrouter_model_failed_trying_next",
                    model=model,
                    error_type=type(e).__name__,
                    error_message=str(e),
                )
                continue

        # Semua model gagal
        raise ExternalAPIError(
            f"Semua model OpenRouter gagal. Last error: {last_error}",
            status_code=503,
        )

    def _call_api(self, model: str, prompt: str, system_prompt: str = "") -> str:
        """HTTP call ke OpenRouter API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hermes.local",
            "X-Title": "Hermes YouTube Agent",
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )

            if response.status_code in (429, 500, 502, 503, 504):
                raise ExternalAPIError(
                    f"OpenRouter {model} return {response.status_code}",
                    status_code=response.status_code,
                )

            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()

        except httpx.HTTPStatusError as e:
            raise ExternalAPIError(
                f"OpenRouter {model} HTTP error: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.TimeoutException as e:
            raise ExternalAPIError(
                f"OpenRouter timeout setelah {self._timeout} detik (model: {model})",
                status_code=408,
            ) from e
        except httpx.RequestError as e:
            raise ExternalAPIError(
                f"OpenRouter connection error (model: {model}): {e}",
                status_code=0,
            ) from e
