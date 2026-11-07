"""Add account-scoped favorite jobs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260816_05"
down_revision: Union[str, None] = "20260814_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The portable SQL snapshot may already contain this table before Alembic
    # records the revision. In that case the snapshot is authoritative.
    if sa.inspect(op.get_bind()).has_table("favorite_jobs"):
        return
    op.create_table(
        "favorite_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role_id", sa.String(length=80), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("role_field", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_favorite_jobs_user_role"),
    )
    op.create_index("ix_favorite_jobs_user_id", "favorite_jobs", ["user_id"], unique=False)
    op.create_index("ix_favorite_jobs_role_id", "favorite_jobs", ["role_id"], unique=False)


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("favorite_jobs"):
        return
    op.drop_index("ix_favorite_jobs_role_id", table_name="favorite_jobs")
    op.drop_index("ix_favorite_jobs_user_id", table_name="favorite_jobs")
    op.drop_table("favorite_jobs")
