"""
app/schemas/queue.py
Pydantic schemas untuk upload queue API.
"""
from datetime import datetime

from pydantic import BaseModel


class VideoTagResponse(BaseModel):
    tag: str
    position: int
    source: str

    model_config = {"from_attributes": True}


class QueueItemResponse(BaseModel):
    id: int
    channel_id: int
    staging_path: str
    title_final: str | None
    description_final: str | None
    title_generated: str | None
    description_generated: str | None
    is_human_override: bool
    category_id: str | None
    made_for_kids: bool
    is_altered_content: bool
    playlist_id: str | None
    priority: int
    status: str
    scheduled_time: datetime | None
    youtube_video_id: str | None
    retry_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    tags: list[VideoTagResponse] = []

    model_config = {"from_attributes": True}


class MetadataOverride(BaseModel):
    """Human override untuk metadata video."""
    title: str
    description: str
    category_id: str | None = "10"
    made_for_kids: bool = False
    is_altered_content: bool = False
    playlist_id: str | None = None
    save_as_preset: bool = False


class RequeueRequest(BaseModel):
    """Request untuk re-queue video dari FAILED_PERMANENT."""
    reason: str = "Manual re-queue from dashboard"


class ReorderRequest(BaseModel):
    """Request untuk mengurutkan antrean."""
    direction: str
