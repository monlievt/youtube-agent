"""
app/services/metrics_service.py
Service untuk mengumpulkan dan mengekspos metrik sistem format Prometheus.
"""
import os
import shutil
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from prometheus_client import CollectorRegistry, Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST

from app.models.queue import UploadQueue
from app.models.system import SystemAuditLog
from app.repositories.queue_repo import QueueRepository
from app.core.config import get_settings

settings = get_settings()

# Registry khusus agar tidak bentrok dengan default registry
registry = CollectorRegistry()

# 1. Gauge untuk Queue Depth berdasarkan status
queue_depth_gauge = Gauge(
    "hermes_queue_depth",
    "Jumlah item di upload queue berdasarkan status",
    ["status"],
    registry=registry
)

# 2. Counter untuk total upload error
upload_errors_counter = Counter(
    "hermes_upload_errors_total",
    "Total kegagalan upload",
    registry=registry
)

# 3. Gauge untuk Disk Usage Percentage
disk_usage_gauge = Gauge(
    "hermes_disk_usage_percent",
    "Persentase penggunaan ruang disk",
    ["path"],
    registry=registry
)

# 4. Gauge untuk Worker Heartbeat (timestamp epoch worker terakhir aktif)
worker_heartbeat_gauge = Gauge(
    "hermes_worker_heartbeat_epoch",
    "Timestamp epoch keaktifan worker terakhir",
    registry=registry
)


class MetricsService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._queue_repo = QueueRepository(session)

    async def collect_metrics(self) -> bytes:
        """
        Kumpulkan metrik dari database, storage, dan redis, lalu generate format Prometheus.
        """
        # A. Hitung queue depth dari DB secara dinamis
        statuses = [
            "PENDING", "METADATA_READY", "AWAITING_APPROVAL", "SCHEDULED",
            "UPLOADING", "PRIVATE_UPLOADED", "THUMBNAIL_ATTACHED",
            "SCHEDULED_PUBLIC", "DONE", "THUMBNAIL_FAILED", "FAILED_PERMANENT",
            "PAUSED", "PAUSED_EXTERNAL", "QUOTA_EXHAUSTED", "NEEDS_REAUTH"
        ]
        
        # Reset gauge values first
        for status in statuses:
            queue_depth_gauge.labels(status=status).set(0)

        # Query counts group by status
        result = await self._session.execute(
            select(UploadQueue.status, func.count(UploadQueue.id))
            .where(UploadQueue.deleted_at.is_(None))
            .group_by(UploadQueue.status)
        )
        for status, count in result.all():
            queue_depth_gauge.labels(status=status).set(count)

        # B. Dapatkan total error dari audit log
        error_count_res = await self._session.execute(
            select(func.count(SystemAuditLog.id))
            .where(SystemAuditLog.action == "upload_failed")
        )
        total_errors = error_count_res.scalar() or 0
        # Sync counter value
        upload_errors_counter._value.set(total_errors)

        # C. Hitung disk usage untuk staging_path
        staging_dir = settings.staging_path
        if os.path.exists(staging_dir):
            try:
                total, used, free = shutil.disk_usage(staging_dir)
                percent = (used / total) * 100.0
                disk_usage_gauge.labels(path="staging").set(percent)
            except Exception:
                pass

        # D. Ambil worker heartbeat dari redis
        import redis
        try:
            r = redis.Redis.from_url(settings.redis_url)
            val = r.get("hermes:worker:heartbeat")
            if val:
                worker_heartbeat_gauge.set(int(val))
        except Exception:
            pass
        
        return generate_latest(registry)
