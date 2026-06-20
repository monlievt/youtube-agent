"""
app/models/channel.py
Models: channels, channel_credentials
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, BigInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_name: Mapped[str] = mapped_column(String(100), nullable=False)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    genre: Mapped[str] = mapped_column(String(50), nullable=False)
    gcp_project_id: Mapped[str] = mapped_column(String(50), default="project_default", nullable=False)
    trust_level: Mapped[str] = mapped_column(
        Enum("NEW", "TRUSTED", name="trust_level_enum"),
        default="NEW",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    youtube_thumbnail_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    youtube_subscribers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    youtube_views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    youtube_video_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    youtube_videos_cache: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    credential: Mapped["ChannelCredential | None"] = relationship(
        "ChannelCredential", back_populates="channel", uselist=False
    )
    upload_queue: Mapped[list["UploadQueue"]] = relationship(  # type: ignore[name-defined]
        "UploadQueue", back_populates="channel"
    )
    metadata_patterns: Mapped[list["MetadataPattern"]] = relationship(
        "MetadataPattern", back_populates="channel", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("channel_name", name="uq_channel_name"),
    )

    def __repr__(self) -> str:
        return f"<Channel id={self.id} name={self.channel_name!r} trust={self.trust_level}>"

    @property
    def auth_status(self) -> str | None:
        """
        Baca auth_status dari ChannelCredential.
        Diperlukan agar ChannelResponse schema bisa serialize field ini
        (field ada di tabel channel_credentials, bukan channels).
        """
        from sqlalchemy import inspect
        try:
            insp = inspect(self)
            if insp and "credential" in insp.unloaded:
                return None
        except Exception:
            return None
        if self.credential and not self.credential.deleted_at:
            return self.credential.auth_status
        return None

    @property
    def scanner_path(self) -> str:
        """
        Path pemantauan folder scanner untuk channel ini.
        """
        from app.core.config import get_settings
        settings = get_settings()
        import os
        subfolder = self.folder_name if self.folder_name else self.channel_name
        return os.path.join(settings.nfs_videos_path, subfolder)


class ChannelCredential(Base):
    __tablename__ = "channel_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    # Semua nilai dienkripsi di aplikasi sebelum disimpan (RULE-005)
    encrypted_client_id: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_data_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_refreshed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auth_status: Mapped[str] = mapped_column(
        Enum("VALID", "NEEDS_REAUTH", "REVOKED", name="auth_status_enum"),
        default="VALID",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="credential")

    __table_args__ = (
        UniqueConstraint("channel_id", name="uq_channel_credential"),
    )


class MetadataPattern(Base):
    __tablename__ = "metadata_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    title_template: Mapped[str] = mapped_column(String(200), nullable=False)
    description_template: Mapped[str] = mapped_column(Text, nullable=False)
    tags_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="metadata_patterns")

