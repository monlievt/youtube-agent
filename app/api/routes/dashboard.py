"""
app/api/routes/dashboard.py
Dashboard metrics API — global stats, GCP quota, storage usage, and audit logs.
"""
from fastapi import APIRouter
from sqlalchemy import select, func
import shutil

from app.api.dependencies import CurrentUser, DBSession
from app.core.logging import get_logger
from app.core.config import get_settings
from app.models.channel import Channel
from app.models.system import GcpQuotaTracker, SystemAuditLog

log = get_logger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(db: DBSession, user: CurrentUser):
    """Mengembalikan semua data untuk widgets di dashboard utama."""
    # 1. Metrik Global (Subs, Views, Videos)
    metrics_result = await db.execute(
        select(
            func.sum(Channel.youtube_subscribers),
            func.sum(Channel.youtube_views),
            func.sum(Channel.youtube_video_count)
        ).where(Channel.is_active.is_(True), Channel.deleted_at.is_(None))
    )
    metrics = metrics_result.all()[0]
    
    total_subs = int(metrics[0] or 0)
    total_views = int(metrics[1] or 0)
    total_videos = int(metrics[2] or 0)

    # 2. Quota API Tracker
    quota_result = await db.execute(
        select(GcpQuotaTracker)
        .order_by(GcpQuotaTracker.last_updated.desc())
        .limit(1)
    )
    quota_tracker = quota_result.scalar_one_or_none()
    
    quota_used = 0
    quota_limit = 10000
    if quota_tracker:
        quota_used = quota_tracker.units_used_today
        quota_limit = quota_tracker.units_limit

    # 3. Storage capacity (Staging & NFS)
    storage_path = settings.nfs_videos_path
    total_space = 0
    used_space = 0
    free_space = 0
    pct_used = 0.0
    
    try:
        total, used, free = shutil.disk_usage(storage_path)
        total_space = total
        used_space = used
        free_space = free
        pct_used = round((used / total) * 100, 1) if total > 0 else 0.0
    except Exception as e:
        log.warning("failed_to_check_disk_usage", path=storage_path, error=str(e))

    # 4. Recent activities (5 log terakhir)
    logs_result = await db.execute(
        select(SystemAuditLog)
        .order_by(SystemAuditLog.created_at.desc())
        .limit(5)
    )
    audit_logs = logs_result.scalars().all()
    
    recent_activities = []
    for l in audit_logs:
        recent_activities.append({
            "id": l.id,
            "actor": l.actor,
            "action": l.action,
            "resource_type": l.resource_type,
            "created_at": l.created_at.isoformat(),
            "details": l.details
        })

    return {
        "global_metrics": {
            "subscribers": total_subs,
            "views": total_views,
            "videos": total_videos
        },
        "quota": {
            "used": quota_used,
            "limit": quota_limit,
            "percentage": round((quota_used / quota_limit) * 100, 1) if quota_limit > 0 else 0.0
        },
        "storage": {
            "total_gb": round(total_space / (1024**3), 1),
            "used_gb": round(used_space / (1024**3), 1),
            "free_gb": round(free_space / (1024**3), 1),
            "percentage_used": pct_used
        },
        "recent_activities": recent_activities
    }
