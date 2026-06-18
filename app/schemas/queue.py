"""
app/schemas/queue.py
Pydantic schemas untuk upload queue API.
"""
from datetime import datetime

from pydantic import BaseModel


class QueueItemResponse(BaseModel):
    id: int
    channel_id: int
    staging_path: str
    title_final: str | None
    status: str
    scheduled_time: datetime | None
    youtube_video_id: str | None
    retry_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MetadataOverride(BaseModel):
    """Human override untuk metadata video."""
    title: str
    description: str


class RequeueRequest(BaseModel):
    """Request untuk re-queue video dari FAILED_PERMANENT."""
    reason: str = "Manual re-queue from dashboard"
