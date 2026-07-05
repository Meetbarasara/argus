"""initial schema — vector extension + all tables + indexes (03 §1)

Revision ID: 0001
Revises:
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

from argus.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector must exist before the memories table / HNSW index are created (08 #8)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
