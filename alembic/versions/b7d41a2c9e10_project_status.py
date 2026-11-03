"""project status (active / inactive / closed) replaces archived

Revision ID: b7d41a2c9e10
Revises: cafe3870b9b7
Create Date: 2026-11-01 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401


revision: str = "b7d41a2c9e10"
down_revision: Union[str, Sequence[str], None] = "cafe3870b9b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="active"))
        batch.add_column(sa.Column("status_changed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))
    op.execute("UPDATE project SET status = 'closed' WHERE archived = 1")
    with op.batch_alter_table("project") as batch:
        batch.drop_column("archived")
        batch.create_index("ix_project_status", ["status"])


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE project SET archived = 1 WHERE status = 'closed'")
    with op.batch_alter_table("project") as batch:
        batch.drop_index("ix_project_status")
        batch.drop_column("status_changed_at")
        batch.drop_column("status")
