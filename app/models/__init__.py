"""
app/models/__init__.py
Export semua models agar Alembic bisa detect saat autogenerate.
"""
from app.models.channel import Channel, ChannelCredential
from app.models.queue import UploadQueue, VideoTag, UploadAttempt
from app.models.history import MetadataHistory, UploadStateHistory
from app.models.system import SystemConfig, SystemAuditLog, GcpQuotaTracker
from app.models.file import FileChecksum
from app.models.analytics import (
    AnalyticsLog,
    VideoEvaluation,
    EvaluationOption,
    TimeslotPerformance,
    ThumbnailStyle,
    VideoTracklist,
)

__all__ = [
    "Channel",
    "ChannelCredential",
    "UploadQueue",
    "VideoTag",
    "UploadAttempt",
    "MetadataHistory",
    "UploadStateHistory",
    "SystemConfig",
    "SystemAuditLog",
    "GcpQuotaTracker",
    "FileChecksum",
    "AnalyticsLog",
    "VideoEvaluation",
    "EvaluationOption",
    "TimeslotPerformance",
    "ThumbnailStyle",
    "VideoTracklist",
]
