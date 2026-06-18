"""
app/api/routes/health.py
Health check endpoints: /health (liveness) dan /ready (readiness).
Sesuai blueprint: wajib ada di Tier 1.
"""
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", summary="Liveness check")
async def health() -> dict:
    """
    Liveness probe — return 200 jika proses hidup.
    Docker/Kubernetes: jika gagal, restart container.
    """
    return {"status": "ok", "service": "hermes"}


@router.get("/ready", summary="Readiness check")
async def ready() -> dict:
    """
    Readiness probe — cek DB, Redis, NFS.
    Return 200 hanya jika semua dependencies OK.
    """
    checks: dict[str, str] = {}
    all_ok = True

    # Check Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        all_ok = False
        log.error("readiness_db_failed", error_message=str(e))

    # Check Redis
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        all_ok = False
        log.error("readiness_redis_failed", error_message=str(e))

    # Check NFS
    nfs_path = settings.nfs_videos_path
    if os.path.exists(nfs_path):
        checks["nfs"] = "ok"
    else:
        checks["nfs"] = "unavailable (mount not found)"
        # NFS tidak wajib untuk readiness — sistem masih bisa jalan tanpa NFS
        log.warning("readiness_nfs_unavailable", nfs_path=nfs_path)

    # Check Worker Heartbeat
    try:
        r = aioredis.from_url(settings.redis_url)
        hb = await r.get("hermes:worker:heartbeat")
        await r.aclose()
        if hb:
            import time
            diff = int(time.time()) - int(hb)
            if diff < 120:  # Worker aktif jika heartbeat < 2 menit
                checks["worker"] = "ok"
            else:
                checks["worker"] = f"warning: stale heartbeat ({diff}s ago)"
        else:
            checks["worker"] = "warning: no heartbeat recorded"
    except Exception as e:
        checks["worker"] = f"error: {type(e).__name__}"
        all_ok = False

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/metrics", summary="Prometheus Metrics")
async def metrics(response: Response = None) -> Response:
    """
    Prometheus metrics endpoint.
    Mengekspos metrik antrean, error, kapasitas disk, dan heartbeat worker.
    """
    from fastapi import Response
    from app.core.database import AsyncSessionLocal
    from app.services.metrics_service import MetricsService
    
    async with AsyncSessionLocal() as session:
        service = MetricsService(session)
        content = await service.collect_metrics()
        
    return Response(content=content, media_type="text/plain; version=0.0.4")

