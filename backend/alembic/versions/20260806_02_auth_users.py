"""Add local application users.

Revision ID: 20260806_02
Revises: 20260805_01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_02"
down_revision: Union[str, None] = "20260805_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_users_role"), "app_users", ["role"], unique=False)
    op.create_index(op.f("ix_app_users_username"), "app_users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_app_users_username"), table_name="app_users")
    op.drop_index(op.f("ix_app_users_role"), table_name="app_users")
    op.drop_table("app_users")
