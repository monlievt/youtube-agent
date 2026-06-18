"""
app/services/evaluator_service.py
Service untuk evaluasi H+24 dan H+7.
Menggunakan diagnosis 4-langkah dan OpenRouter untuk membuat rekomendasi.
"""
import json
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.gateways.openrouter_gateway import OpenRouterGateway
from app.models.analytics import AnalyticsLog, VideoEvaluation, EvaluationOption, TimeslotPerformance
from app.repositories.analytics_repo import AnalyticsRepository
from app.repositories.queue_repo import QueueRepository
from app.repositories.config_repo import ConfigRepository

log = get_logger(__name__)


class EvaluatorService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._analytics_repo = AnalyticsRepository(session)
        self._queue_repo = QueueRepository(session)
        self._config_repo = ConfigRepository(session)

    async def evaluate_video(self, queue_id: int, log_type: str) -> VideoEvaluation:
        """
        Lakukan evaluasi terhadap video berdasarkan logs terbaru.
        """
        # Ambil data logs terbaru untuk video ini
        queue_item = await self._queue_repo.get_by_id(queue_id)
        if not queue_item or not queue_item.youtube_video_id:
            raise ValueError(f"Queue item {queue_id} tidak valid")

        # Ambil log terbaru untuk log_type ini
        result = await self._session.execute(
            select(AnalyticsLog)
            .where(
                AnalyticsLog.youtube_video_id == queue_item.youtube_video_id,
                AnalyticsLog.log_type == log_type
            )
            .order_by(AnalyticsLog.pulled_at.desc())
            .limit(1)
        )
        latest_log = result.scalar_one_or_none()
        if not latest_log:
            raise ValueError(f"Log {log_type} untuk video {queue_item.youtube_video_id} tidak ditemukan")

        # Ambil baseline channel
        baseline_ctr, baseline_avd = await self._analytics_repo.get_channel_baseline(
            queue_item.channel_id, log_type
        )

        # Hitung threshold dari config
        min_ctr = await self._config_repo.get_float("min_ctr_threshold")

        # Jika baseline kosong, gunakan default
        if baseline_ctr == 0.0:
            baseline_ctr = min_ctr
        if baseline_avd == 0.0:
            baseline_avd = 180.0  # default 3 menit

        # Hitung score (0-100)
        # Formula sederhana: Bobot 50% CTR relative, 50% AVD relative
        ctr_ratio = min(latest_log.ctr_percentage / baseline_ctr, 2.0) if baseline_ctr > 0 else 1.0
        avd_ratio = min(latest_log.avd_seconds / baseline_avd, 2.0) if baseline_avd > 0 else 1.0
        performance_score = round(((ctr_ratio + avd_ratio) / 2.0) * 100.0, 1)

        # Diagnosis 4-Langkah
        diagnosis = ""
        recommended_action = "KEEP"
        eval_status = "ANALYZED"

        ctr_healthy = latest_log.ctr_percentage >= baseline_ctr
        avd_healthy = latest_log.avd_seconds >= baseline_avd

        if ctr_healthy and avd_healthy:
            diagnosis = "Performa CTR dan AVD di atas baseline channel. Video sehat."
            recommended_action = "KEEP"
            eval_status = "CLOSED"
        elif not ctr_healthy and avd_healthy:
            diagnosis = f"CTR ({latest_log.ctr_percentage}%) di bawah baseline ({round(baseline_ctr, 1)}%), tetapi retensi (AVD) bagus. Judul atau thumbnail kurang menarik minat klik."
            recommended_action = "CHANGE_TITLE"
            eval_status = "ACTION_REQUIRED"
        elif ctr_healthy and not avd_healthy:
            diagnosis = f"CTR bagus, tetapi retensi penonton (AVD: {latest_log.avd_seconds}s) di bawah baseline ({round(baseline_avd, 1)}s). Penonton cepat keluar, kemungkinan hook awal video kurang kuat."
            recommended_action = "CHECK_CONTENT"
            eval_status = "CLOSED"  # Content tidak bisa diubah pasca-upload
        else:
            diagnosis = "CTR dan retensi penonton (AVD) keduanya di bawah baseline. Perlu perbaikan metadata komprehensif."
            recommended_action = "CHANGE_MULTIPLE"
            eval_status = "ACTION_REQUIRED"

        # Simpan evaluasi ke DB
        eval_record = VideoEvaluation(
            queue_id=queue_id,
            youtube_video_id=queue_item.youtube_video_id,
            eval_stage=log_type,
            views=latest_log.views,
            impressions=latest_log.impressions,
            ctr_percentage=latest_log.ctr_percentage,
            avd_seconds=latest_log.avd_seconds,
            baseline_ctr=baseline_ctr,
            baseline_avd=baseline_avd,
            performance_score=performance_score,
            diagnosis_summary=diagnosis,
            hermes_confidence=0.85,
            recommended_action=recommended_action,
            eval_status=eval_status,
        )

        saved_eval = await self._analytics_repo.create_evaluation(eval_record)

        # Jika butuh perubahan judul/metadata, panggil OpenRouter untuk alternatif judul
        if recommended_action in ["CHANGE_TITLE", "CHANGE_MULTIPLE"]:
            try:
                openrouter = OpenRouterGateway()
                prompt = (
                    f"Diberikan video YouTube genre {queue_item.channel.genre} dengan "
                    f"judul saat ini: '{queue_item.title_final or queue_item.title_generated}'.\n"
                    f"Deskripsi saat ini: '{queue_item.description_final or queue_item.description_generated}'.\n"
                    f"Video ini memiliki performa klik (CTR) yang rendah. Tolong generate 1 judul alternatif "
                    f"yang sangat menarik (high CTR) untuk target audiens genre ini.\n"
                    f"Format output harus berupa JSON mentah dengan satu key 'title':\n"
                    f'{{"title": "Judul Baru Yang Menarik"}}'
                )
                system_prompt = "Anda adalah AI ahli optimasi metadata YouTube (SEO & CTR)."

                response, model_used = openrouter.generate_text(prompt, system_prompt)
                
                # Coba parse JSON
                try:
                    # Bersihkan json markdown block jika ada
                    if "```json" in response:
                        response = response.split("```json")[1].split("```")[0].strip()
                    elif "```" in response:
                        response = response.split("```")[1].split("```")[0].strip()
                    
                    data = json.loads(response.strip())
                    new_title = data.get("title", "")
                except Exception:
                    new_title = response.strip()

                if new_title:
                    option = EvaluationOption(
                        evaluation_id=saved_eval.id,
                        option_type="TITLE",
                        option_value=new_title,
                        is_selected=False
                    )
                    self._session.add(option)
                    await self._session.flush()

            except Exception as e:
                log.error("evaluator_openrouter_failed_to_generate_alternative", queue_id=queue_id, error=str(e))

        log.info(
            "video_evaluated",
            queue_id=queue_id,
            performance_score=performance_score,
            recommended_action=recommended_action,
            eval_status=eval_status,
        )

        # Update timeslot performance jika data valid (clean sample)
        if queue_item.scheduled_time:
            await self._update_timeslot(
                channel_id=queue_item.channel_id,
                scheduled_time=queue_item.scheduled_time,
                views_48h=latest_log.views,
                ctr=latest_log.ctr_percentage,
                avd=latest_log.avd_seconds
            )

        return saved_eval

    async def _update_timeslot(
        self, channel_id: int, scheduled_time: datetime, views_48h: int, ctr: float, avd: int
    ) -> None:
        """Update performa slot posting."""
        dow = scheduled_time.weekday()  # 0 = Monday, 6 = Sunday
        hour = scheduled_time.hour

        perf = await self._analytics_repo.get_timeslot_performance(channel_id, dow, hour)
        if not perf:
            perf = TimeslotPerformance(
                channel_id=channel_id,
                hour_of_day=hour,
                day_of_week=dow,
                avg_views_48h=float(views_48h),
                avg_ctr=ctr,
                avg_avd_seconds=avd,
                sample_count=1,
                confidence_score=0.1,
                last_updated=datetime.utcnow()
            )
            await self._analytics_repo.save_timeslot_performance(perf)
        else:
            # Hitung rata-rata baru
            count = perf.sample_count
            perf.avg_views_48h = (perf.avg_views_48h * count + views_48h) / (count + 1)
            perf.avg_ctr = (perf.avg_ctr * count + ctr) / (count + 1)
            perf.avg_avd_seconds = int((perf.avg_avd_seconds * count + avd) / (count + 1))
            perf.sample_count = count + 1
            # Confidence score naik seiring naiknya sample_count
            perf.confidence_score = min(float(perf.sample_count) / 10.0, 1.0)
            perf.last_updated = datetime.utcnow()
            await self._session.flush()
