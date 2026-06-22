"""007_add_presets_and_queue_features

Revision ID: 007
Revises: 006
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── upload_queue ──────────────────────────────────────────────
    op.add_column("upload_queue", sa.Column("category_id", sa.String(length=50), nullable=True, server_default="10"))
    op.add_column("upload_queue", sa.Column("made_for_kids", sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()))
    op.add_column("upload_queue", sa.Column("is_altered_content", sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()))
    op.add_column("upload_queue", sa.Column("playlist_id", sa.String(length=100), nullable=True))
    op.add_column("upload_queue", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))

    # ── metadata_patterns ─────────────────────────────────────────
    op.add_column("metadata_patterns", sa.Column("category_id", sa.String(length=50), nullable=False, server_default="10"))
    op.add_column("metadata_patterns", sa.Column("made_for_kids", sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()))
    op.add_column("metadata_patterns", sa.Column("is_altered_content", sa.Boolean(), nullable=False, server_default=sa.sql.expression.false()))
    op.add_column("metadata_patterns", sa.Column("playlist_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    # ── metadata_patterns ─────────────────────────────────────────
    op.drop_column("metadata_patterns", "playlist_id")
    op.drop_column("metadata_patterns", "is_altered_content")
    op.drop_column("metadata_patterns", "made_for_kids")
    op.drop_column("metadata_patterns", "category_id")

    # ── upload_queue ──────────────────────────────────────────────
    op.drop_column("upload_queue", "priority")
    op.drop_column("upload_queue", "playlist_id")
    op.drop_column("upload_queue", "is_altered_content")
    op.drop_column("upload_queue", "made_for_kids")
    op.drop_column("upload_queue", "category_id")
