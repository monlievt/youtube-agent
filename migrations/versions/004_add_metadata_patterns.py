"""004_add_metadata_patterns

Revision ID: 004
Revises: 003
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Buat tabel metadata_patterns
    op.create_table(
        "metadata_patterns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("title_template", sa.String(length=200), nullable=False),
        sa.Column("description_template", sa.Text(), nullable=False),
        sa.Column("tags_template", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Tambah kolom pattern_id ke tabel upload_queue
    op.add_column(
        "upload_queue",
        sa.Column("pattern_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_upload_queue_pattern_id",
        "upload_queue",
        "metadata_patterns",
        ["pattern_id"],
        ["id"],
        ondelete="SET NULL"
    )


def downgrade() -> None:
    # 1. Hapus foreign key dan kolom dari upload_queue
    op.drop_constraint("fk_upload_queue_pattern_id", "upload_queue", type_="foreignkey")
    op.drop_column("upload_queue", "pattern_id")

    # 2. Hapus tabel metadata_patterns
    op.drop_table("metadata_patterns")
