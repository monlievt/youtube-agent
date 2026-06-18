"""003_add_envelope_encryption

Revision ID: 003
Revises: 2bbed0d238fc
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "003"
down_revision = "2bbed0d238fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Menambahkan kolom encrypted_data_key ke tabel channel_credentials
    op.add_column(
        "channel_credentials",
        sa.Column("encrypted_data_key", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    # Menghapus kolom encrypted_data_key dari tabel channel_credentials
    op.drop_column("channel_credentials", "encrypted_data_key")
