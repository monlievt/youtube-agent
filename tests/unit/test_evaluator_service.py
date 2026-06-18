"""
tests/unit/test_evaluator_service.py
Unit tests untuk EvaluatorService.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from sqlalchemy import select

from app.models.channel import Channel
from app.models.queue import UploadQueue
from app.models.analytics import AnalyticsLog, VideoEvaluation
from app.services.evaluator_service import EvaluatorService


@pytest.mark.asyncio
async def test_calculate_performance_score_and_diagnosis(db_session):
    """
    Uji coba kalkulasi score evaluasi dan penentuan diagnosis performa.
    """
    # 1. Setup mock data
    channel = Channel(channel_name="Test Lofi", genre="lofi")
    db_session.add(channel)
    await db_session.flush()

    from app.models.file import FileChecksum
    checksum = FileChecksum(channel_id=channel.id, sha256="abc123test", filename="test.mp4")
    db_session.add(checksum)
    await db_session.flush()

    queue_item = UploadQueue(
        channel_id=channel.id,
        file_checksum_id=checksum.id,
        staging_path="/tmp/staging/test.mp4",
        youtube_video_id="yt_123",
        status="DONE",
        scheduled_time=datetime.utcnow()
    )
    db_session.add(queue_item)
    await db_session.flush()

    # Log metrics
    log_record = AnalyticsLog(
        youtube_video_id="yt_123",
        channel_id=channel.id,
        log_type="H24",
        views=150,
        impressions=3000,
        ctr_percentage=1.5,  # Rendah dibanding baseline (5.0%)
        avd_seconds=120,    # Tinggi (AVD ok)
    )
    db_session.add(log_record)
    
    # Tambahkan log history untuk baseline
    baseline_log = AnalyticsLog(
        youtube_video_id="yt_old",
        channel_id=channel.id,
        log_type="H24",
        views=200,
        impressions=4000,
        ctr_percentage=5.0,  # Baseline CTR = 5.0%
        avd_seconds=100,    # Baseline AVD = 100s
    )
    db_session.add(baseline_log)
    await db_session.flush()

    # Mock OpenRouterGateway agar tidak memicu pemanggilan API eksternal
    mock_openrouter = MagicMock()
    mock_openrouter.generate_text.return_value = ('{"title": "Lofi Chill Beats New title"}', "mock-model")

    with patch("app.services.evaluator_service.OpenRouterGateway", return_value=mock_openrouter):
        evaluator = EvaluatorService(db_session)
        evaluation = await evaluator.evaluate_video(queue_item.id, "H24")

        # Verifikasi hasil diagnosis
        assert evaluation.performance_score > 0
        assert evaluation.recommended_action == "CHANGE_TITLE"  # Karena CTR di bawah baseline, AVD di atas baseline
        assert evaluation.eval_status == "ACTION_REQUIRED"

        # Query options secara eksplisit untuk menghindari lazy loading error
        from app.models.analytics import EvaluationOption
        res_opt = await db_session.execute(
            select(EvaluationOption).where(EvaluationOption.evaluation_id == evaluation.id)
        )
        options = res_opt.scalars().all()
        assert len(options) == 1
        assert options[0].option_value == "Lofi Chill Beats New title"
