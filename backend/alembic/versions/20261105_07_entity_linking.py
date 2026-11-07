"""Add extraction, normalization and entity linking outputs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_07"
down_revision: Union[str, None] = "20261105_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_if_missing(name: str, columns: list, indexes: list[tuple[str, list[str]]], unique: tuple[str, list[str]] | None = None) -> None:
    if sa.inspect(op.get_bind()).has_table(name):
        return
    constraints = [sa.UniqueConstraint(*unique[1], name=unique[0])] if unique else []
    op.create_table(name, *columns, *constraints)
    for index_name, fields in indexes:
        op.create_index(index_name, name, fields)


def upgrade() -> None:
    _create_if_missing("extracted_records", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("raw_record_id", sa.String(64), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("parser_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ], [("ix_extracted_records_batch_id", ["batch_id"]), ("ix_extracted_records_raw_record_id", ["raw_record_id"])],
       ("uq_extracted_batch_raw", ["batch_id", "raw_record_id"]))
    _create_if_missing("normalized_records", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("raw_record_id", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("linker_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ], [("ix_normalized_records_batch_id", ["batch_id"]), ("ix_normalized_records_raw_record_id", ["raw_record_id"])],
       ("uq_normalized_batch_raw", ["batch_id", "raw_record_id"]))
    _create_if_missing("entity_links", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("raw_record_id", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("surface_form", sa.String(500), nullable=False),
        sa.Column("normalized_surface_form", sa.String(500), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("entity_origin", sa.String(24), nullable=False, server_default="asset"),
        sa.Column("linker_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ], [("ix_entity_links_batch_id", ["batch_id"]), ("ix_entity_links_raw_record_id", ["raw_record_id"]),
        ("ix_entity_links_entity_type", ["entity_type"]), ("ix_entity_links_status", ["status"])],
       ("uq_entity_links_batch_raw_type_surface", ["batch_id", "raw_record_id", "entity_type", "normalized_surface_form"]))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, indexes in (
        ("entity_links", ("ix_entity_links_status", "ix_entity_links_entity_type", "ix_entity_links_raw_record_id", "ix_entity_links_batch_id")),
        ("normalized_records", ("ix_normalized_records_raw_record_id", "ix_normalized_records_batch_id")),
        ("extracted_records", ("ix_extracted_records_raw_record_id", "ix_extracted_records_batch_id")),
    ):
        if inspector.has_table(table):
            for index in indexes:
                op.drop_index(index, table_name=table)
            op.drop_table(table)
