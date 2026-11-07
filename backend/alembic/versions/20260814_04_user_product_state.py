"""Persist account profiles, resume ownership, and talent assessment batches."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_04"
down_revision: Union[str, None] = "20260807_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resume_profiles", sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""))
    op.create_index("ix_resume_profiles_user_id", "resume_profiles", ["user_id"], unique=False)
    op.create_table(
        "user_workspace_profiles",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("audience", sa.String(length=24), nullable=False, server_default="seeker"),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("hr_evaluation_settings", sa.JSON(), nullable=False),
        sa.Column("work_style_assessment", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "talent_assessment_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role_id", sa.String(length=80), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_talent_assessment_batches_user_id", "talent_assessment_batches", ["user_id"], unique=False)
    op.create_index("ix_talent_assessment_batches_role_id", "talent_assessment_batches", ["role_id"], unique=False)
    op.create_table(
        "talent_assessment_candidates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_code", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("resume_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("match_report_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="completed"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_talent_assessment_candidates_batch_id", "talent_assessment_candidates", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_talent_assessment_candidates_batch_id", table_name="talent_assessment_candidates")
    op.drop_table("talent_assessment_candidates")
    op.drop_index("ix_talent_assessment_batches_role_id", table_name="talent_assessment_batches")
    op.drop_index("ix_talent_assessment_batches_user_id", table_name="talent_assessment_batches")
    op.drop_table("talent_assessment_batches")
    op.drop_table("user_workspace_profiles")
    op.drop_index("ix_resume_profiles_user_id", table_name="resume_profiles")
    op.drop_column("resume_profiles", "user_id")
