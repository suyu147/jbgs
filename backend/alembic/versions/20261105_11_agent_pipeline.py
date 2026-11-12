"""Add local agent orchestration runs and draft descriptions."""

from alembic import op
import sqlalchemy as sa

revision = "20261105_11"
down_revision = "20261105_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("batch_id", sa.String(64), nullable=False),
            sa.Column("draft_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("trigger", sa.String(40), nullable=False, server_default="ingest"),
            sa.Column("scope", sa.String(24), nullable=False, server_default="batch"),
            sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
            sa.Column("stages", sa.JSON(), nullable=False),
            sa.Column("draft_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("description_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_used", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
    if not inspector.has_table("agent_descriptions"):
        op.create_table(
            "agent_descriptions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("draft_id", sa.String(64), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(24), nullable=False, server_default="rules"),
            sa.Column("model", sa.String(120), nullable=False, server_default=""),
            sa.Column("prompt_version", sa.String(80), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="rules"),
            sa.Column("llm_error", sa.Text(), nullable=False),
            sa.Column("sections", sa.JSON(), nullable=False),
            sa.Column("markdown_path", sa.Text(), nullable=False),
            sa.Column("docx_path", sa.Text(), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("draft_id", name="uq_agent_descriptions_draft_id"),
        )
    for table, columns in (("agent_runs", ("batch_id", "draft_id", "status")), ("agent_descriptions", ("draft_id",))):
        existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
        for column in columns:
            name = f"ix_{table}_{column}"
            if name not in existing:
                op.create_index(name, table, [column])


def downgrade() -> None:
    for table in ("agent_descriptions", "agent_runs"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
