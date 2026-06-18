"""
app/core/config.py
Konfigurasi aplikasi dari environment variables + system_config DB.
Sesuai RULE-002: semua konfigurasi di sini, tidak ada default tersembunyi.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Settings dari environment variables (.env).
    Semua key wajib ada di .env.example.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Abaikan env vars yang tidak didefinisikan (e.g. MYSQL_USER untuk docker)
    )

    # Database
    database_url: str
    mysql_database: str = "hermes"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Celery
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # Encryption
    hermes_master_key: str

    # OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Storage paths
    nfs_videos_path: str = "/mnt/omv-videos"
    nfs_archive_path: str = "/mnt/omv-archive"
    nfs_thumbnails_path: str = "/mnt/omv-thumbnails"
    nfs_backups_path: str = "/mnt/omv-backups"
    staging_path: str = "/var/staging"

    # App
    app_env: str = "development"
    secret_key: str
    dashboard_username: str = "admin"
    dashboard_password: str

    # Logging
    log_level: str = "INFO"

    # Alerting
    discord_webhook_url: str | None = None



@lru_cache
def get_settings() -> Settings:
    """Singleton settings — di-cache setelah pertama kali dipanggil."""
    return Settings()
