"""
app/models/analytics.py
Models for Tier 2: analytics_logs, video_evaluations, evaluation_options,
timeslot_performance, thumbnail_styles, video_tracklist
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, Float,
    String, Text, UniqueConstraint, Index, func, CHAR
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AnalyticsLog(Base):
    __tablename__ = "analytics_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_video_id: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    log_type: Mapped[str] = mapped_column(
        Enum("H24", "H48", "H7", "H14", "H28", "H90", name="log_type_enum"),
        nullable=False,
    )
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr_percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avd_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pulled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel")  # type: ignore[name-defined]

    __table_args__ = (
        Index("idx_video_type", "youtube_video_id", "log_type"),
        Index("idx_channel_pulled", "channel_id", "pulled_at"),
    )


class VideoEvaluation(Base):
    __tablename__ = "video_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    youtube_video_id: Mapped[str] = mapped_column(String(50), nullable=False)
    eval_stage: Mapped[str] = mapped_column(
        Enum("H24", "H48", "H7", "H14", "H28", "H90", name="log_type_enum"),
        nullable=False,
    )
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr_percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avd_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_avd: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnosis_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hermes_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(
        Enum(
            "KEEP", "CHANGE_THUMBNAIL", "CHANGE_TITLE",
            "CHANGE_DESCRIPTION", "CHANGE_MULTIPLE",
            "CHECK_CONTENT", "WAIT_MORE_DATA",
            name="recommended_action_enum"
        ),
        nullable=True,
    )
    eval_status: Mapped[str] = mapped_column(
        Enum("PENDING", "ANALYZED", "ACTION_REQUIRED", "ACTION_TAKEN", "CLOSED", name="eval_status_enum"),
        default="PENDING",
        nullable=False,
    )
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    queue_item: Mapped["UploadQueue"] = relationship("UploadQueue")  # type: ignore[name-defined]
    options: Mapped[list["EvaluationOption"]] = relationship(
        "EvaluationOption", back_populates="evaluation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_queue_stage", "queue_id", "eval_stage"),
        Index("idx_eval_status", "eval_status", "created_at"),
    )


class EvaluationOption(Base):
    __tablename__ = "evaluation_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("video_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    option_type: Mapped[str] = mapped_column(
        Enum("TITLE", "DESCRIPTION", "THUMBNAIL", name="option_type_enum"),
        nullable=False,
    )
    option_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    evaluation: Mapped["VideoEvaluation"] = relationship("VideoEvaluation", back_populates="options")

    __table_args__ = (
        Index("idx_eval_type", "evaluation_id", "option_type"),
    )


class TimeslotPerformance(Base):
    __tablename__ = "timeslot_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False)  # TINYINT
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # TINYINT
    avg_views_48h: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_avd_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("channel_id", "day_of_week", "hour_of_day", name="uq_channel_slot"),
        Index("idx_channel_confidence", "channel_id", "confidence_score"),
    )


class ThumbnailStyle(Base):
    __tablename__ = "thumbnail_styles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    style_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avg_ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VideoTracklist(Base):
    __tablename__ = "video_tracklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    track_position: Mapped[int] = mapped_column(Integer, nullable=False)  # TINYINT
    track_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_queue_tracks", "queue_id"),
    )
