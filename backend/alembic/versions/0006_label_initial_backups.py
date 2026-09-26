"""label existing first backups as initial

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26 10:00:00

Before this release a device's first backup was reported like a change (reason "manual (UI)",
author = whoever last ran a command on the device). Relabel those records.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE config_backups b
        SET reason = CASE
                WHEN b.reason IS NULL OR b.reason ILIKE 'initial%' THEN 'Initial backup'
                ELSE 'Initial backup (' || b.reason || ')'
            END,
            author = 'networkops-backup'
        WHERE b.changed
          AND NOT EXISTS (
              SELECT 1 FROM config_backups e
              WHERE e.device_id = b.device_id AND e.changed AND e.collected_at < b.collected_at
          )
        """
    )


def downgrade() -> None:
    pass
