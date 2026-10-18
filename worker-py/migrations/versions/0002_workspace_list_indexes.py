"""Index workspace-filtered list ordering without blocking live PostgreSQL writes.

Revision ID: 0002_workspace_list_indexes
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_workspace_list_indexes"
down_revision = "0001_platform"
branch_labels = None
depends_on = None
TABLES = ("agents", "contacts", "calls", "campaigns", "staff_tasks", "audit_events")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        # Concurrent indexes cannot be built inside a transaction.
        with op.get_context().autocommit_block():
            for table in TABLES:
                op.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_{table}_workspace_created_id ON {table} (workspace_id, created_at DESC, id)"
                )
    else:
        for table in TABLES:
            op.create_index(
                f"ix_{table}_workspace_created_id",
                table,
                ["workspace_id", sa.text("created_at DESC"), "id"],
                if_not_exists=True,
            )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for table in TABLES:
                op.execute(
                    f"DROP INDEX CONCURRENTLY IF EXISTS ix_{table}_workspace_created_id"
                )
    else:
        for table in TABLES:
            op.drop_index(
                f"ix_{table}_workspace_created_id", table_name=table, if_exists=True
            )
