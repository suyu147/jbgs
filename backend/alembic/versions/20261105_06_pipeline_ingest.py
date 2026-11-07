"""Create the first data-governance ingest tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_06"
down_revision: Union[str, None] = "20260816_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pipeline_batches"):
        op.create_table(
            "pipeline_batches",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("source_type", sa.String(32), nullable=False),
            sa.Column("source_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("dataset_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("status", sa.String(24), nullable=False, server_default="received"),
            sa.Column("stage", sa.String(40), nullable=False, server_default="ingest"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("statistics", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_pipeline_batches_status", "pipeline_batches", ["status"])
    if not inspector.has_table("pipeline_stage_logs"):
        op.create_table(
            "pipeline_stage_logs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("batch_id", sa.String(64), nullable=False),
            sa.Column("stage", sa.String(40), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("statistics", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_pipeline_stage_logs_batch_id", "pipeline_stage_logs", ["batch_id"])
    if not inspector.has_table("raw_records"):
        op.create_table(
            "raw_records",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("batch_id", sa.String(64), nullable=False),
            sa.Column("source_record_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("node_type", sa.String(64), nullable=False, server_default=""),
            sa.Column("source_canonical", sa.String(255), nullable=False, server_default=""),
            sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("raw_payload", sa.JSON(), nullable=False),
            sa.Column("source_locator", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_of", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_raw_records_batch_id", "raw_records", ["batch_id"])
        op.create_index("ix_raw_records_source_record_id", "raw_records", ["source_record_id"])
        op.create_index("ix_raw_records_content_sha256", "raw_records", ["content_sha256"])
    else:
        raw_columns = {column["name"] for column in inspector.get_columns("raw_records")}
        if "created_at" not in raw_columns:
            op.add_column("raw_records", sa.Column("created_at", sa.DateTime(), nullable=True))
        if "observation_count" not in raw_columns:
            op.add_column("raw_records", sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("raw_records"):
        for name in ("ix_raw_records_content_sha256", "ix_raw_records_source_record_id", "ix_raw_records_batch_id"):
            op.drop_index(name, table_name="raw_records")
        op.drop_table("raw_records")
    if inspector.has_table("pipeline_stage_logs"):
        op.drop_index("ix_pipeline_stage_logs_batch_id", table_name="pipeline_stage_logs")
        op.drop_table("pipeline_stage_logs")
    if inspector.has_table("pipeline_batches"):
        op.drop_index("ix_pipeline_batches_status", table_name="pipeline_batches")
        op.drop_table("pipeline_batches")
