"""005_add_youtube_channel_sync_columns

Revision ID: 005
Revises: 004
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("youtube_thumbnail_url", sa.String(length=255), nullable=True))
    op.add_column("channels", sa.Column("youtube_subscribers", sa.Integer(), server_default="0", nullable=False))
    op.add_column("channels", sa.Column("youtube_views", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("channels", sa.Column("youtube_video_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("channels", sa.Column("youtube_videos_cache", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "youtube_videos_cache")
    op.drop_column("channels", "youtube_video_count")
    op.drop_column("channels", "youtube_views")
    op.drop_column("channels", "youtube_subscribers")
    op.drop_column("channels", "youtube_thumbnail_url")
