"""Add feature snapshots and period signals."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_08"
down_revision: Union[str, None] = "20261105_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("feature_snapshots"):
        op.create_table(
            "feature_snapshots",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("period_key", sa.String(32), nullable=False),
            sa.Column("granularity", sa.String(16), nullable=False, server_default="month"),
            sa.Column("cohort_key", sa.String(255), nullable=False),
            sa.Column("cohort_basis", sa.String(16), nullable=False, server_default="title"),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("input_summary", sa.JSON(), nullable=False),
            sa.Column("feature_version", sa.String(40), nullable=False, server_default="feature-v1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("period_key", "granularity", "cohort_key", name="uq_feature_snapshots_period_cohort"),
        )
        op.create_index("ix_feature_snapshots_period_key", "feature_snapshots", ["period_key"])
        op.create_index("ix_feature_snapshots_cohort_key", "feature_snapshots", ["cohort_key"])
    if not inspector.has_table("signals"):
        op.create_table(
            "signals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("signal_type", sa.String(40), nullable=False),
            sa.Column("cohort_key", sa.String(255), nullable=False),
            sa.Column("period_key", sa.String(32), nullable=False),
            sa.Column("granularity", sa.String(16), nullable=False, server_default="month"),
            sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("suppression_key", sa.String(255), nullable=False, server_default=""),
            sa.Column("signal_version", sa.String(40), nullable=False, server_default="signal-v1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("signal_type", "cohort_key", "period_key", "granularity", name="uq_signals_type_cohort_period"),
        )
        for name, column in (("ix_signals_signal_type", "signal_type"), ("ix_signals_cohort_key", "cohort_key"),
                             ("ix_signals_period_key", "period_key"), ("ix_signals_status", "status"),
                             ("ix_signals_suppression_key", "suppression_key")):
            op.create_index(name, "signals", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("signals"):
        for name in ("ix_signals_suppression_key", "ix_signals_status", "ix_signals_period_key", "ix_signals_cohort_key", "ix_signals_signal_type"):
            op.drop_index(name, table_name="signals")
        op.drop_table("signals")
    if inspector.has_table("feature_snapshots"):
        op.drop_index("ix_feature_snapshots_cohort_key", table_name="feature_snapshots")
        op.drop_index("ix_feature_snapshots_period_key", table_name="feature_snapshots")
        op.drop_table("feature_snapshots")
