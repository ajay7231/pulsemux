"""Initial persistent platform schema.

Revision ID: 0001_platform
"""

from alembic import op
from app.platform.models import Base

revision = "0001_platform"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    # Downgrading deliberately requires an explicit database backup/restore.
    raise RuntimeError(
        "Restore a verified backup to remove the initial platform schema"
    )
