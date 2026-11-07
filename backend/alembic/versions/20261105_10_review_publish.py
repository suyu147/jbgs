"""Add review comments, MySQL versions and publish compensation tasks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_10"
down_revision: Union[str, None] = "20261105_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_if_missing(table: str, name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(table) and name not in {item["name"] for item in inspector.get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("review_comments"):
        op.create_table(
            "review_comments",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("draft_id", sa.String(64), nullable=False),
            sa.Column("action", sa.String(24), nullable=False, server_default=""),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("author_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _index_if_missing("review_comments", "ix_review_comments_draft_id", ["draft_id"])

    if not inspector.has_table("role_definition_versions"):
        op.create_table(
            "role_definition_versions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("version_id", sa.String(64), nullable=False),
            sa.Column("draft_id", sa.String(64), nullable=False),
            sa.Column("role_id", sa.String(80), nullable=False, server_default=""),
            sa.Column("role_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("candidate_type", sa.String(40), nullable=False, server_default="new_role"),
            sa.Column("status", sa.String(24), nullable=False, server_default="approved"),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("origin", sa.String(24), nullable=False, server_default="legacy"),
            sa.Column("batch_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("evidence_grade", sa.String(32), nullable=False, server_default="legacy"),
            sa.Column("publish_result", sa.JSON(), nullable=False),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("version_id", name="uq_role_definition_versions_version_id"),
        )
    for name, column in (
        ("ix_role_definition_versions_version_id", "version_id"),
        ("ix_role_definition_versions_draft_id", "draft_id"),
        ("ix_role_definition_versions_role_id", "role_id"),
        ("ix_role_definition_versions_status", "status"),
        ("ix_role_definition_versions_origin", "origin"),
        ("ix_role_definition_versions_batch_id", "batch_id"),
    ):
        _index_if_missing("role_definition_versions", name, [column])

    if not inspector.has_table("publish_tasks"):
        op.create_table(
            "publish_tasks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("version_id", sa.String(64), nullable=False),
            sa.Column("draft_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("idempotency_key", name="uq_publish_tasks_idempotency_key"),
        )
    for name, column in (
        ("ix_publish_tasks_idempotency_key", "idempotency_key"),
        ("ix_publish_tasks_version_id", "version_id"),
        ("ix_publish_tasks_draft_id", "draft_id"),
        ("ix_publish_tasks_status", "status"),
    ):
        _index_if_missing("publish_tasks", name, [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, indexes in (
        ("publish_tasks", ("ix_publish_tasks_status", "ix_publish_tasks_draft_id", "ix_publish_tasks_version_id", "ix_publish_tasks_idempotency_key")),
        ("role_definition_versions", ("ix_role_definition_versions_batch_id", "ix_role_definition_versions_origin", "ix_role_definition_versions_status", "ix_role_definition_versions_role_id", "ix_role_definition_versions_draft_id", "ix_role_definition_versions_version_id")),
        ("review_comments", ("ix_review_comments_draft_id",)),
    ):
        if inspector.has_table(table):
            existing = {item["name"] for item in inspector.get_indexes(table)}
            for name in indexes:
                if name in existing:
                    op.drop_index(name, table_name=table)
            op.drop_table(table)
