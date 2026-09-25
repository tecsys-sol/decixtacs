"""tacacs agent status, rancid configs

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-25 09:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tacacs_servers", sa.Column("running_sha256", sa.String(length=64), nullable=True))
    op.add_column("tacacs_servers", sa.Column("agent_status", sa.String(length=16), nullable=True))
    op.add_column("tacacs_servers", sa.Column("agent_message", sa.Text(), nullable=True))
    op.create_table(
        "rancid_configs",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rancid_group", sa.String(length=128), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_index(op.f("ix_rancid_configs_device_id"), "rancid_configs", ["device_id"], unique=False)
    op.create_index(op.f("ix_rancid_configs_tenant_id"), "rancid_configs", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rancid_configs_tenant_id"), table_name="rancid_configs")
    op.drop_index(op.f("ix_rancid_configs_device_id"), table_name="rancid_configs")
    op.drop_table("rancid_configs")
    op.drop_column("tacacs_servers", "agent_message")
    op.drop_column("tacacs_servers", "agent_status")
    op.drop_column("tacacs_servers", "running_sha256")
