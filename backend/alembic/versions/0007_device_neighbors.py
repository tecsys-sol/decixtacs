"""LLDP neighbours collected with the backups

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_neighbors",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("local_interface", sa.String(length=128), nullable=False),
        sa.Column("remote_system", sa.String(length=255), nullable=True),
        sa.Column("remote_port", sa.String(length=255), nullable=True),
        sa.Column("remote_port_description", sa.String(length=255), nullable=True),
        sa.Column("remote_chassis", sa.String(length=128), nullable=True),
        sa.Column("remote_address", sa.String(length=64), nullable=True),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_neighbors_device_id"), "device_neighbors", ["device_id"], unique=False)
    op.create_index(op.f("ix_device_neighbors_tenant_id"), "device_neighbors", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_device_neighbors_tenant_id"), table_name="device_neighbors")
    op.drop_index(op.f("ix_device_neighbors_device_id"), table_name="device_neighbors")
    op.drop_table("device_neighbors")
