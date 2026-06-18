"""
app/api/routes/evaluations.py
Evaluations management API — list evaluations, apply options, reject/close.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException

from app.api.dependencies import CurrentUser, DBSession
from app.core.logging import get_logger
from app.gateways.youtube_gateway import YouTubeGateway
from app.models.history import MetadataHistory
from app.models.analytics import VideoEvaluation, EvaluationOption
from app.repositories.analytics_repo import AnalyticsRepository
from app.repositories.queue_repo import QueueRepository
from app.services.credential_service import CredentialService

log = get_logger(__name__)
router = APIRouter(prefix="/api/evaluations", tags=["Evaluations"])


@router.get("")
async def list_evaluations(db: DBSession, user: CurrentUser):
    """List semua evaluasi yang butuh tindakan atau baru selesai dianalisis."""
    repo = AnalyticsRepository(db)
    evals = await repo.get_all_active_evaluations()
    
    result = []
    for ev in evals:
        result.append({
            "id": ev.id,
            "queue_id": ev.queue_id,
            "youtube_video_id": ev.youtube_video_id,
            "eval_stage": ev.eval_stage,
            "views": ev.views,
            "impressions": ev.impressions,
            "ctr_percentage": ev.ctr_percentage,
            "avd_seconds": ev.avd_seconds,
            "baseline_ctr": ev.baseline_ctr,
            "baseline_avd": ev.baseline_avd,
            "performance_score": ev.performance_score,
            "diagnosis_summary": ev.diagnosis_summary,
            "recommended_action": ev.recommended_action,
            "eval_status": ev.eval_status,
            "created_at": ev.created_at,
            "channel_name": ev.queue_item.channel.channel_name if ev.queue_item and ev.queue_item.channel else "Unknown",
            "options": [
                {
                    "id": opt.id,
                    "option_type": opt.option_type,
                    "option_value": opt.option_value,
                    "is_selected": opt.is_selected
                } for opt in ev.options
            ]
        })
    return result


@router.post("/{eval_id}/apply-option")
async def apply_evaluation_option(
    eval_id: int,
    option_id: int,
    db: DBSession,
    user: CurrentUser
) -> dict:
    """Terapkan judul/metadata rekomendasi AI ke YouTube API dan database."""
    analytics_repo = AnalyticsRepository(db)
    queue_repo = QueueRepository(db)
    credential_service = CredentialService(db)

    evaluation = await analytics_repo.get_evaluation_by_id(eval_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluasi tidak ditemukan")

    if evaluation.eval_status not in ("PENDING", "ACTION_REQUIRED"):
        raise HTTPException(status_code=400, detail="Evaluasi sudah diproses atau ditutup")

    # Ambil option yang sesuai
    selected_option = None
    for opt in evaluation.options:
        if opt.id == option_id:
            selected_option = opt
            break

    if not selected_option:
        raise HTTPException(status_code=404, detail="Opsi rekomendasi tidak ditemukan untuk evaluasi ini")

    queue_item = evaluation.queue_item
    channel_id = queue_item.channel_id
    youtube_video_id = queue_item.youtube_video_id

    # Update metadata di YouTube
    client_id, client_secret, refresh_token = (
        await credential_service.get_decrypted_credentials(
            channel_id, actor=f"human:{user}"
        )
    )

    yt = YouTubeGateway(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        channel_id=channel_id,
    )

    if selected_option.option_type == "TITLE":
        # Panggil API YouTube untuk update judul
        log.info("updating_youtube_video_title_via_evaluation", queue_id=queue_item.id, title=selected_option.option_value)
        
        old_title = queue_item.title_final or queue_item.title_generated
        queue_item.title_final = selected_option.option_value
        
        # YouTube update snippet
        # Catatan: update video di YouTube Gateway membutuhkan Snippet penuh. Kita bisa memanggil set_scheduled atau update_video custom,
        # tapi di YouTubeGateway kita bisa langsung memanggil update untuk titles.
        # Mari gunakan service._service.videos().update.
        # YouTubeGateway class kita memiliki set_scheduled, tapi tidak ada update_title.
        # Mari panggil update_title secara inline menggunakan service internal YouTubeGateway
        try:
            # Ambil snippet saat ini agar tidak menghapus description/tags
            video_data = yt._service.videos().list(
                part="snippet",
                id=youtube_video_id
            ).execute()
            
            if video_data.get("items"):
                snippet = video_data["items"][0]["snippet"]
                snippet["title"] = selected_option.option_value
                
                yt._service.videos().update(
                    part="snippet",
                    body={
                        "id": youtube_video_id,
                        "snippet": snippet
                    }
                ).execute()
            else:
                raise HTTPException(status_code=404, detail="Video tidak ditemukan di YouTube")
        except Exception as e:
            log.error("failed_to_update_title_on_youtube", error=str(e))
            raise HTTPException(status_code=502, detail=f"Gagal mengupdate judul di YouTube: {e}")

        # Catat history
        await queue_repo.write_metadata_history(
            MetadataHistory(
                queue_id=queue_item.id,
                field_name="title",
                old_value=old_title,
                new_value=selected_option.option_value,
                changed_by="HUMAN",
                change_reason=f"Applied AI recommended option from evaluation {eval_id} (stage: {evaluation.eval_stage}) by {user}",
            )
        )

    # Set status
    selected_option.is_selected = True
    evaluation.eval_status = "ACTION_TAKEN"
    evaluation.action_taken_at = datetime.utcnow()

    log.info(
        "evaluation_option_applied",
        eval_id=eval_id,
        option_id=option_id,
        actor=user,
    )
    return {"status": "applied", "eval_id": eval_id, "option_id": option_id}


@router.post("/{eval_id}/reject")
async def reject_evaluation(eval_id: int, db: DBSession, user: CurrentUser) -> dict:
    """Tolak / abaikan rekomendasi evaluasi."""
    analytics_repo = AnalyticsRepository(db)
    evaluation = await analytics_repo.get_evaluation_by_id(eval_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluasi tidak ditemukan")

    evaluation.eval_status = "CLOSED"
    
    log.info("evaluation_rejected", eval_id=eval_id, actor=user)
    return {"status": "rejected", "eval_id": eval_id}
