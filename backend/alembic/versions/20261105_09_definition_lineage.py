"""Add M4 definition lineage fields to role definition drafts."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_09"
down_revision: Union[str, None] = "20261105_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_if_missing(table: str, column: sa.Column, index_name: str | None = None) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return
    existing = {item["name"] for item in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)
    if index_name:
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        if index_name not in indexes:
            op.create_index(index_name, table, [column.name])


def upgrade() -> None:
    _add_if_missing(
        "role_definition_drafts",
        sa.Column("origin", sa.String(24), nullable=False, server_default="legacy"),
        "ix_role_definition_drafts_origin",
    )
    _add_if_missing(
        "role_definition_drafts",
        sa.Column("batch_id", sa.String(64), nullable=False, server_default=""),
        "ix_role_definition_drafts_batch_id",
    )
    _add_if_missing(
        "role_definition_drafts",
        sa.Column("evidence_grade", sa.String(32), nullable=False, server_default="legacy"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("role_definition_drafts"):
        return
    columns = {item["name"] for item in inspector.get_columns("role_definition_drafts")}
    indexes = {item["name"] for item in inspector.get_indexes("role_definition_drafts")}
    for index_name in ("ix_role_definition_drafts_batch_id", "ix_role_definition_drafts_origin"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="role_definition_drafts")
    for column_name in ("evidence_grade", "batch_id", "origin"):
        if column_name in columns:
            op.drop_column("role_definition_drafts", column_name)
