"""
app/workers/celery_app.py
Celery instance — satu-satunya scheduler (tidak ada APScheduler).
Sesuai blueprint: Celery + Redis, Celery Beat untuk semua schedule.
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hermes",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.crawler_tasks",
        "app.workers.metadata_tasks",
        "app.workers.thumbnail_tasks",
        "app.workers.upload_tasks",
        "app.workers.analytics_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # Acknowledge setelah task selesai (bukan saat mulai)
    worker_prefetch_multiplier=1,  # Satu task per worker — hindari starvation
    task_soft_time_limit=1800,     # 30 menit soft limit (sesuai blueprint)
    task_time_limit=2100,          # 35 menit hard limit
    # Retry default
    task_max_retries=3,
    task_default_retry_delay=60,
)

# ── Celery Beat Schedule ──────────────────────────────────────
# Satu-satunya scheduler. Tidak ada cron system lain.
celery_app.conf.beat_schedule = {
    # Scan NFS setiap 1 jam untuk file baru
    "scan-omv-storage": {
        "task": "app.workers.crawler_tasks.scan_omv_storage",
        "schedule": crontab(minute="0"),  # Setiap jam tepat
    },

    # Proses upload yang sudah dijadwalkan (setiap 2 menit)
    "process-scheduled-uploads": {
        "task": "app.workers.upload_tasks.process_scheduled_uploads",
        "schedule": 120.0,  # 2 menit
    },

    # Proses metadata untuk item PENDING (setiap 5 menit)
    "process-pending-metadata": {
        "task": "app.workers.metadata_tasks.process_pending_metadata",
        "schedule": 300.0,  # 5 menit
    },

    # Deteksi UPLOADING yang stuck (setiap 5 menit)
    "detect-stuck-uploads": {
        "task": "app.workers.upload_tasks.detect_stuck_uploads",
        "schedule": 300.0,
    },

    # Auto-cancel AWAITING_APPROVAL yang expired (setiap jam)
    "cancel-expired-approvals": {
        "task": "app.workers.upload_tasks.cancel_expired_approvals",
        "schedule": crontab(minute="30"),
    },

    # Reset quota harian (tengah malam UTC)
    "reset-daily-quota": {
        "task": "app.workers.upload_tasks.reset_daily_quota",
        "schedule": crontab(hour="0", minute="5"),
    },

    # Scan & schedule analytics pulls (setiap jam)
    "schedule-analytics-pulls": {
        "task": "app.workers.analytics_tasks.schedule_analytics_pulls_task",
        "schedule": crontab(minute="15"),  # Setiap jam menit 15
    },

    # Worker heartbeat (setiap 30 detik)
    "worker-heartbeat": {
        "task": "app.workers.upload_tasks.worker_heartbeat_task",
        "schedule": 30.0,
    },
}
