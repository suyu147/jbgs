"""Track uploaded dataset revisions and graph synchronization.

Revision ID: 20260807_03
Revises: 20260806_02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_03"
down_revision: Union[str, None] = "20260806_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_revisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("record_count", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sync_status", sa.String(length=24), nullable=False),
        sa.Column("sync_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_revisions_dataset_id", "dataset_revisions", ["dataset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dataset_revisions_dataset_id", table_name="dataset_revisions")
    op.drop_table("dataset_revisions")
