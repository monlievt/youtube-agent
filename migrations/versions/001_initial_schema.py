"""001_initial_schema

Revision ID: 001
Revises: 
Create Date: 2026-06-17

Migration pertama: semua tabel Tier 1 + seed data system_config.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── channels ──────────────────────────────────────────────────
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_name", sa.String(100), nullable=False),
        sa.Column("youtube_channel_id", sa.String(50), nullable=True),
        sa.Column("genre", sa.String(50), nullable=False),
        sa.Column("gcp_project_id", sa.String(50), server_default="project_default"),
        sa.Column("trust_level", sa.Enum("NEW", "TRUSTED", name="trust_level_enum"), server_default="NEW"),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("channel_name", name="uq_channel_name"),
    )

    # ── channel_credentials ──────────────────────────────────────
    op.create_table(
        "channel_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("encrypted_client_id", sa.Text, nullable=False),
        sa.Column("encrypted_client_secret", sa.Text, nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text, nullable=False),
        sa.Column("key_version", sa.Integer, server_default="1"),
        sa.Column("last_refreshed", sa.DateTime, nullable=True),
        sa.Column("auth_status", sa.Enum("VALID", "NEEDS_REAUTH", "REVOKED", name="auth_status_enum"), server_default="VALID"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("channel_id", name="uq_channel_credential"),
    )

    # ── file_checksums ────────────────────────────────────────────
    op.create_table(
        "file_checksums",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=True),
        sa.Column("detected_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "sha256", name="uq_channel_sha256"),
    )
    op.create_index("idx_sha256", "file_checksums", ["sha256"])

    # ── upload_queue ──────────────────────────────────────────────
    op.create_table(
        "upload_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("file_checksum_id", sa.Integer, sa.ForeignKey("file_checksums.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("staging_path", sa.String(500), nullable=False),
        sa.Column("thumbnail_path", sa.String(500), nullable=True),
        sa.Column("title_generated", sa.String(100), nullable=True),
        sa.Column("description_generated", sa.Text, nullable=True),
        sa.Column("title_final", sa.String(100), nullable=True),
        sa.Column("description_final", sa.Text, nullable=True),
        sa.Column("is_human_override", sa.Boolean, server_default=sa.false()),
        sa.Column("status", sa.Enum(
            "PENDING", "METADATA_READY", "AWAITING_APPROVAL", "SCHEDULED",
            "UPLOADING", "PRIVATE_UPLOADED", "THUMBNAIL_ATTACHED",
            "SCHEDULED_PUBLIC", "DONE", "THUMBNAIL_FAILED", "FAILED_PERMANENT",
            "PAUSED", "PAUSED_EXTERNAL", "QUOTA_EXHAUSTED", "NEEDS_REAUTH",
            name="upload_status_enum",
        ), server_default="PENDING"),
        sa.Column("previous_status", sa.String(50), nullable=True),
        sa.Column("scheduled_time", sa.DateTime, nullable=True),
        sa.Column("actual_publish_hour", sa.Integer, nullable=True),
        sa.Column("actual_publish_dow", sa.Integer, nullable=True),
        sa.Column("youtube_video_id", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime, nullable=True),
        sa.Column("locked_at", sa.DateTime, nullable=True),
        sa.Column("worker_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("channel_id", "file_checksum_id", name="uq_channel_file"),
    )
    op.create_index("idx_status_scheduled", "upload_queue", ["status", "scheduled_time"])
    op.create_index("idx_channel_status", "upload_queue", ["channel_id", "status", "scheduled_time"])

    # ── video_tags ────────────────────────────────────────────────
    op.create_table(
        "video_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("queue_id", sa.Integer, sa.ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tag", sa.String(30), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("source", sa.Enum("AI", "HUMAN", name="tag_source_enum"), server_default="AI"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_queue_tags", "video_tags", ["queue_id"])

    # ── upload_attempts ───────────────────────────────────────────
    op.create_table(
        "upload_attempts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("queue_id", sa.Integer, sa.ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.CHAR(36), nullable=False),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("attempt_type", sa.Enum("VIDEO", "THUMBNAIL", "SCHEDULE", name="attempt_type_enum"), nullable=False),
        sa.Column("youtube_video_id", sa.String(50), nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("response_summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("success", sa.Boolean, server_default=sa.false()),
        sa.UniqueConstraint("idempotency_key", name="uq_idempotency"),
    )
    op.create_index("idx_queue_attempts", "upload_attempts", ["queue_id", "attempt_type"])

    # ── metadata_history ──────────────────────────────────────────
    op.create_table(
        "metadata_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("queue_id", sa.Integer, sa.ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("field_name", sa.Enum("title", "description", "tags", "thumbnail", "status", name="history_field_enum"), nullable=False),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("changed_by", sa.Enum("AI", "HUMAN", "SYSTEM", name="changed_by_enum"), nullable=False),
        sa.Column("change_reason", sa.String(255), nullable=True),
        sa.Column("changed_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_queue_history", "metadata_history", ["queue_id", "field_name"])

    # ── upload_state_history ──────────────────────────────────────
    op.create_table(
        "upload_state_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("queue_id", sa.Integer, sa.ForeignKey("upload_queue.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_state", sa.String(50), nullable=True),
        sa.Column("to_state", sa.String(50), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("actor", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_queue_state", "upload_state_history", ["queue_id", "created_at"])

    # ── system_config ─────────────────────────────────────────────
    op.create_table(
        "system_config",
        sa.Column("config_key", sa.String(100), primary_key=True),
        sa.Column("config_value", sa.String(500), nullable=False),
        sa.Column("config_type", sa.Enum("INT", "FLOAT", "STRING", "BOOL", name="config_type_enum"), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Seed data system_config (sesuai blueprint)
    op.bulk_insert(
        sa.table(
            "system_config",
            sa.column("config_key", sa.String),
            sa.column("config_value", sa.String),
            sa.column("config_type", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"config_key": "max_retry_count",          "config_value": "3",    "config_type": "INT",    "description": "Maksimal retry sebelum FAILED_PERMANENT"},
            {"config_key": "openrouter_timeout_sec",   "config_value": "30",   "config_type": "INT",    "description": "Timeout request ke OpenRouter (detik)"},
            {"config_key": "default_publish_hour_utc", "config_value": "15",   "config_type": "INT",    "description": "Jam publish default UTC (=22 WIB) jika belum ada timeslot data"},
            {"config_key": "min_ctr_threshold",        "config_value": "2.0",  "config_type": "FLOAT",  "description": "CTR minimum yang dianggap sehat (%)"},
            {"config_key": "h24_views_threshold",      "config_value": "100",  "config_type": "INT",    "description": "Views H+24 di bawah ini trigger evaluasi"},
            {"config_key": "upload_timeout_minutes",   "config_value": "30",   "config_type": "INT",    "description": "Timeout UPLOADING state sebelum dianggap stuck"},
            {"config_key": "disk_warning_percent",     "config_value": "80",   "config_type": "INT",    "description": "Disk usage % untuk warning"},
            {"config_key": "disk_halt_percent",        "config_value": "90",   "config_type": "INT",    "description": "Disk usage % untuk halt ingestion"},
            {"config_key": "circuit_breaker_errors",   "config_value": "5",    "config_type": "INT",    "description": "Jumlah error sebelum circuit breaker open"},
            {"config_key": "circuit_breaker_wait_sec", "config_value": "300",  "config_type": "INT",    "description": "Detik tunggu sebelum circuit breaker half-open"},
            {"config_key": "approval_timeout_days",    "config_value": "7",    "config_type": "INT",    "description": "Hari sebelum AWAITING_APPROVAL auto-cancel"},
            {"config_key": "openrouter_primary",       "config_value": "meta-llama/llama-3.3-70b-instruct:free", "config_type": "STRING", "description": "Model utama OpenRouter"},
            {"config_key": "openrouter_fallback",      "config_value": "mistralai/mistral-7b-instruct:free",     "config_type": "STRING", "description": "Model fallback OpenRouter"},
            {"config_key": "openrouter_last_resort",   "config_value": "google/gemma-2-9b-it:free",              "config_type": "STRING", "description": "Model last resort OpenRouter"},
        ],
    )

    # ── system_audit_log ──────────────────────────────────────────
    op.create_table(
        "system_audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(50), nullable=True),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_resource", "system_audit_log", ["resource_type", "resource_id", "created_at"])
    op.create_index("idx_actor", "system_audit_log", ["actor", "created_at"])

    # ── gcp_quota_tracker ─────────────────────────────────────────
    op.create_table(
        "gcp_quota_tracker",
        sa.Column("project_id", sa.String(50), primary_key=True),
        sa.Column("project_name", sa.String(100), nullable=True),
        sa.Column("units_used_today", sa.Integer, server_default="0"),
        sa.Column("units_limit", sa.Integer, server_default="10000"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("reset_date", sa.Date, nullable=True),
        sa.Column("last_updated", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Seed default GCP project
    op.execute(
        "INSERT INTO gcp_quota_tracker (project_id, project_name, units_limit) "
        "VALUES ('project_default', 'Hermes Project 01', 10000)"
    )


def downgrade() -> None:
    # Drop dalam urutan terbalik (FK dependencies)
    op.drop_table("gcp_quota_tracker")
    op.drop_index("idx_actor", "system_audit_log")
    op.drop_index("idx_resource", "system_audit_log")
    op.drop_table("system_audit_log")
    op.drop_table("system_config")
    op.drop_index("idx_queue_state", "upload_state_history")
    op.drop_table("upload_state_history")
    op.drop_index("idx_queue_history", "metadata_history")
    op.drop_table("metadata_history")
    op.drop_index("idx_queue_attempts", "upload_attempts")
    op.drop_table("upload_attempts")
    op.drop_index("idx_queue_tags", "video_tags")
    op.drop_table("video_tags")
    op.drop_index("idx_channel_status", "upload_queue")
    op.drop_index("idx_status_scheduled", "upload_queue")
    op.drop_table("upload_queue")
    op.drop_index("idx_sha256", "file_checksums")
    op.drop_table("file_checksums")
    op.drop_table("channel_credentials")
    op.drop_table("channels")
