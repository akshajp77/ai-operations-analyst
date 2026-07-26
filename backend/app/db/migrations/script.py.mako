"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

Review checklist before merging this migration:

* Is it reversible? ``downgrade()`` must be implemented, or the deploy cannot
  be rolled back without a restore.
* Is it safe on a live table? ``ALTER TABLE ... ADD COLUMN NOT NULL`` without
  a default rewrites the table and holds an exclusive lock. Add the column
  nullable, backfill in batches, then add the constraint.
* Does it create an index on a large table? Use
  ``op.create_index(..., postgresql_concurrently=True)``, which cannot run
  inside a transaction block.
* Does it drop or rename a column the running application still reads? Deploy
  the code change first; drop in the following release.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
