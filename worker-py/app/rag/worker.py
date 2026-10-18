"""Durable ingestion-only worker. Does not import or run campaign/calling jobs.

Claimed jobs are fenced by a random token and recover after a 30-minute lease.
Chunks become visible atomically in SQL only after every Qdrant batch succeeds.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from uuid import uuid4

from sqlalchemy import delete, or_, select
from ..platform.database import database
from ..platform.models import Audit, Chunk, Document
from .integration import enabled, processor, scoped, source_path, start, stop

logger = logging.getLogger(__name__)


def claim():
    with database().Session() as db:
        doc = db.scalar(
            select(Document)
            .where(
                Document.status != "archived",
                or_(
                    Document.ingestion_status == "queued",
                    (Document.ingestion_status == "processing")
                    & (Document.ingestion_started_at < time.time() - 1800),
                ),
            )
            .order_by(Document.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not doc:
            return None
        doc.ingestion_status = "processing"
        doc.ingestion_started_at = time.time()
        doc.ingestion_token = uuid4().hex
        doc.ingestion_error = None
        db.commit()
        return {
            "id": doc.id,
            "workspace_id": doc.workspace_id,
            "title": doc.title,
            "content": doc.content,
            "source_format": doc.source_format,
            "token": doc.ingestion_token,
            "source": str(source_path(database(), doc)),
        }


async def process(job):
    try:
        from pathlib import Path

        kb = scoped(job["workspace_id"])
        loop = asyncio.get_running_loop()

        def parse():
            kb._processor = processor()
            if Path(job["source"]).exists():
                return kb.processor.parse_document(job["source"], job["title"])
            if job["source_format"] == ".pdf":
                raise FileNotFoundError("Uploaded PDF source is unavailable")
            return job["content"], kb.processor.chunk_markdown(
                job["content"], job["title"]
            )

        content, chunks = await loop.run_in_executor(kb._ingest_pool, parse)
        if len(content) > 200000:
            raise ValueError("Document text exceeds 200,000 characters")
        await kb.ingest_chunks(chunks, document_id=job["id"])
        with database().Session() as db:
            doc = db.scalar(
                select(Document).where(Document.id == job["id"]).with_for_update()
            )
            if (
                not doc
                or doc.ingestion_token != job["token"]
                or doc.status == "archived"
            ):
                return
            db.execute(
                delete(Chunk).where(
                    Chunk.document_id == doc.id, Chunk.workspace_id == doc.workspace_id
                )
            )
            for position, chunk in enumerate(chunks):
                db.add(
                    Chunk(
                        workspace_id=doc.workspace_id,
                        document_id=doc.id,
                        position=position,
                        content=chunk.raw_text,
                        rag_metadata={
                            **chunk.model_dump(),
                            "point_id": kb.point_id(chunk, doc.id),
                        },
                    )
                )
            doc.content = content
            doc.ingestion_status = "ready"
            doc.ingestion_error = None
            db.add(
                Audit(
                    workspace_id=doc.workspace_id,
                    actor_id=None,
                    action="knowledge.ingested",
                    target_id=doc.id,
                    detail={"chunks": len(chunks), "backend": "qdrant"},
                )
            )
            db.commit()
        logger.info("rag_ingestion_completed chunks=%d", len(chunks))
    except Exception as error:
        logger.error("rag_ingestion_failed error_type=%s", type(error).__name__)
        with database().Session() as db:
            doc = db.get(Document, job["id"], with_for_update=True)
            if doc and doc.ingestion_token == job["token"]:
                doc.ingestion_status = "failed"
                doc.ingestion_error = "Parsing or indexing failed. Check worker/model availability and document readability, then retry."
                db.add(
                    Audit(
                        workspace_id=doc.workspace_id,
                        actor_id=None,
                        action="knowledge.ingestion_failed",
                        target_id=doc.id,
                        detail={"error_type": type(error).__name__},
                    )
                )
                db.commit()


async def main():
    if not enabled():
        raise RuntimeError("Set QDRANT_URL before starting the ingestion worker")
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    await start()
    try:
        while not stopping.is_set():
            job = await asyncio.to_thread(claim)
            if job:
                await process(job)
            else:
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
    finally:
        await stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
