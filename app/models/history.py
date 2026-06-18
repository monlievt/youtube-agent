"""
app/models/history.py
Models: metadata_history, upload_state_history
Audit trail untuk semua perubahan — tidak ada perubahan tanpa trace.
"""
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MetadataHistory(Base):
    __tablename__ = "metadata_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(
        Enum("title", "description", "tags", "thumbnail", "status", name="history_field_enum"),
        nullable=False,
    )
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(
        Enum("AI", "HUMAN", "SYSTEM", name="changed_by_enum"),
        nullable=False,
    )
    change_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    queue_item: Mapped["UploadQueue"] = relationship("UploadQueue", back_populates="metadata_history")  # type: ignore[name-defined]

    __table_args__ = (
        Index("idx_queue_history", "queue_id", "field_name"),
    )


class UploadStateHistory(Base):
    """
    Menjawab 'kenapa video ini nyangkut di state X?'
    Setiap transisi state wajib di-log ke sini.
    """
    __tablename__ = "upload_state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    queue_item: Mapped["UploadQueue"] = relationship("UploadQueue", back_populates="state_history")  # type: ignore[name-defined]

    __table_args__ = (
        Index("idx_queue_state", "queue_id", "created_at"),
    )
