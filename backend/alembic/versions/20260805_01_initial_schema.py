"""Create the local application schema.

Revision ID: 20260805_01
Revises:
"""
from typing import Sequence, Union

from alembic import op

from app.database import Base
from app import models  # noqa: F401


revision: str = "20260805_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_all is intentional for the baseline: it adopts the already initialized local schema safely.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
