"""Durable clinical ingestion states and provenance metadata.

Revision ID: 0003_clinical_rag
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_clinical_rag"
down_revision = "0002_workspace_list_indexes"
branch_labels = None
depends_on = None


def upgrade():
    # Initial development installations may already have metadata-created columns.
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("knowledge_documents")
    }
    fields = [
        sa.Column(
            "ingestion_status", sa.String(20), nullable=False, server_default="legacy"
        ),
        sa.Column("ingestion_error", sa.Text()),
        sa.Column("ingestion_started_at", sa.Float()),
        sa.Column("ingestion_token", sa.String(32)),
        sa.Column("source_format", sa.String(12), nullable=False, server_default=".md"),
    ]
    for column in fields:
        if column.name not in columns:
            op.add_column("knowledge_documents", column)
    if "rag_metadata" not in {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("knowledge_chunks")
    }:
        op.add_column("knowledge_chunks", sa.Column("rag_metadata", sa.JSON()))


def downgrade():
    raise RuntimeError("Restore a backup to remove clinical ingestion metadata")
