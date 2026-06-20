"""
app/models/queue.py
Models: upload_queue, video_tags, upload_attempts
State machine upload ada di state machine section blueprint.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CHAR, DateTime, Enum, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Semua status valid untuk upload_queue (sesuai state machine blueprint)
UPLOAD_STATUS = Enum(
    "PENDING",
    "METADATA_READY",
    "AWAITING_APPROVAL",
    "SCHEDULED",
    "UPLOADING",
    "PRIVATE_UPLOADED",
    "THUMBNAIL_ATTACHED",
    "SCHEDULED_PUBLIC",
    "DONE",
    "THUMBNAIL_FAILED",
    "FAILED_PERMANENT",
    "PAUSED",
    "PAUSED_EXTERNAL",
    "QUOTA_EXHAUSTED",
    "NEEDS_REAUTH",
    name="upload_status_enum",
)


class UploadQueue(Base):
    __tablename__ = "upload_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    file_checksum_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("file_checksums.id", ondelete="RESTRICT"), nullable=False
    )
    pattern_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("metadata_patterns.id", ondelete="SET NULL"), nullable=True
    )

    # File paths (relatif dari staging root)
    staging_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Metadata AI-generated
    title_generated: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description_generated: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata final (dipakai saat upload)
    title_final: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_human_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status & scheduling
    status: Mapped[str] = mapped_column(UPLOAD_STATUS, default="PENDING", nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scheduled_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_publish_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_publish_dow: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Hasil upload
    youtube_video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Worker lock
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="upload_queue")  # type: ignore[name-defined]
    file_checksum: Mapped["FileChecksum"] = relationship("FileChecksum", back_populates="upload_queue")  # type: ignore[name-defined]
    metadata_pattern: Mapped["MetadataPattern | None"] = relationship("MetadataPattern")  # type: ignore[name-defined]
    tags: Mapped[list["VideoTag"]] = relationship("VideoTag", back_populates="queue_item", cascade="all, delete-orphan")
    attempts: Mapped[list["UploadAttempt"]] = relationship("UploadAttempt", back_populates="queue_item")
    metadata_history: Mapped[list["MetadataHistory"]] = relationship("MetadataHistory", back_populates="queue_item")  # type: ignore[name-defined]
    state_history: Mapped[list["UploadStateHistory"]] = relationship("UploadStateHistory", back_populates="queue_item")  # type: ignore[name-defined]

    __table_args__ = (
        UniqueConstraint("channel_id", "file_checksum_id", name="uq_channel_file"),
        Index("idx_status_scheduled", "status", "scheduled_time"),
        Index("idx_channel_status", "channel_id", "status", "scheduled_time"),
    )

    def __repr__(self) -> str:
        return f"<UploadQueue id={self.id} status={self.status} channel_id={self.channel_id}>"


class VideoTag(Base):
    __tablename__ = "video_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(30), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        Enum("AI", "HUMAN", name="tag_source_enum"),
        default="AI",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    queue_item: Mapped["UploadQueue"] = relationship("UploadQueue", back_populates="tags")

    __table_args__ = (
        Index("idx_queue_tags", "queue_id"),
    )


class UploadAttempt(Base):
    __tablename__ = "upload_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_type: Mapped[str] = mapped_column(
        Enum("VIDEO", "THUMBNAIL", "SCHEDULE", name="attempt_type_enum"),
        nullable=False,
    )
    youtube_video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    queue_item: Mapped["UploadQueue"] = relationship("UploadQueue", back_populates="attempts")

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_idempotency"),
        Index("idx_queue_attempts", "queue_id", "attempt_type"),
    )
