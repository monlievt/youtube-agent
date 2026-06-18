"""
app/models/system.py
Models: system_config, system_audit_log, gcp_quota_tracker
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, Index,
    Integer, JSON, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemConfig(Base):
    """
    Tidak ada magic number di kode. Semua di sini.
    Sesuai RULE-002: semua konfigurasi harus terdokumentasi dan bisa diubah tanpa deploy.
    """
    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_value: Mapped[str] = mapped_column(String(500), nullable=False)
    config_type: Mapped[str] = mapped_column(
        Enum("INT", "FLOAT", "STRING", "BOOL", name="config_type_enum"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def get_typed_value(self) -> int | float | str | bool:
        """Return value dengan tipe yang benar berdasarkan config_type."""
        match self.config_type:
            case "INT":
                return int(self.config_value)
            case "FLOAT":
                return float(self.config_value)
            case "BOOL":
                return self.config_value.lower() in ("true", "1", "yes")
            case _:
                return self.config_value


class SystemAuditLog(Base):
    """
    Immutable. Tidak ada UPDATE/DELETE pada tabel ini.
    RULE-004: setiap tindakan destruktif harus ada di sini.
    """
    __tablename__ = "system_audit_log"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_resource", "resource_type", "resource_id", "created_at"),
        Index("idx_actor", "actor", "created_at"),
    )


class GcpQuotaTracker(Base):
    """
    Tracking daily quota per GCP project.
    Optimistic locking dengan version column.
    """
    __tablename__ = "gcp_quota_tracker"

    project_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    project_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    units_used_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    units_limit: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reset_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
