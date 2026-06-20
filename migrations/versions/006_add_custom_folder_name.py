"""006_add_custom_folder_name

Revision ID: 006
Revises: 005
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("folder_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "folder_name")
