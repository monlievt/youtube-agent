"""
app/schemas/channel.py
Pydantic schemas untuk channel API requests/responses.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    channel_name: str = Field(max_length=100)
    genre: str = Field(max_length=50)
    youtube_channel_id: str | None = None
    gcp_project_id: str = "project_default"
    trust_level: Literal["NEW", "TRUSTED"] = "NEW"


class ChannelResponse(BaseModel):
    id: int
    channel_name: str
    youtube_channel_id: str | None
    genre: str
    trust_level: str
    is_active: bool
    youtube_thumbnail_url: str | None = None
    youtube_subscribers: int = 0
    youtube_views: int = 0
    youtube_video_count: int = 0
    youtube_videos_cache: str | None = None
    scanner_path: str | None = None
    auth_status: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChannelUpdate(BaseModel):
    trust_level: Literal["NEW", "TRUSTED"] | None = None
    is_active: bool | None = None
    youtube_channel_id: str | None = None
