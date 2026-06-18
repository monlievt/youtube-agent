"""
app/models/file.py
Model: file_checksums — duplicate guard via SHA-256
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, CHAR, DateTime, ForeignKey, Index,
    Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FileChecksum(Base):
    __tablename__ = "file_checksums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    upload_queue: Mapped[list["UploadQueue"]] = relationship(  # type: ignore[name-defined]
        "UploadQueue", back_populates="file_checksum"
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "sha256", name="uq_channel_sha256"),
        Index("idx_sha256", "sha256"),
    )

    def __repr__(self) -> str:
        return f"<FileChecksum id={self.id} sha256={self.sha256[:8]}... file={self.filename!r}>"
