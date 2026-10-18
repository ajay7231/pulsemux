"""Platform bridge; optional heavy dependencies are loaded only when RAG is enabled."""

from __future__ import annotations

import asyncio
import os
import time
from copy import copy

_base = None


def enabled():
    return bool(os.getenv("QDRANT_URL"))


async def start():
    global _base
    if not enabled():
        return
    from .knowledge_base import ClinicalKnowledgeBase

    _base = await asyncio.to_thread(
        ClinicalKnowledgeBase, cache_dir=os.getenv("RAG_MODEL_CACHE", "./model_cache")
    )
    await _base.init_collection()


async def stop():
    global _base
    if _base:
        await _base.close()
        _base = None


def scoped(workspace_id):
    if _base is None:
        raise RuntimeError("Clinical knowledge models are not initialized")
    value = copy(_base)
    value.workspace_id = workspace_id
    return value


def processor():
    if _base is None:
        raise RuntimeError("Clinical knowledge models are not initialized")
    return _base.processor


def source_path(db, document):
    directory = db.data_dir / "rag_sources" / document.workspace_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / (document.id + document.source_format)


async def retrieve_snapshot(workspace_id, snapshot, query, limit=3):
    from ..platform.service import retrieve

    current = [
        chunk
        for chunk in snapshot
        if not chunk.get("expires_at") or chunk["expires_at"] > time.time()
    ]
    indexed = {
        chunk["rag_point_id"]: chunk for chunk in current if chunk.get("rag_point_id")
    }
    if not indexed:
        return retrieve(current, query, limit)
    # A failed vector store must never expand to other protocols or hospital tenants.
    try:
        results = await asyncio.wait_for(
            scoped(workspace_id).retrieve(
                query, top_k=limit, allowed_ids=list(indexed)
            ),
            timeout=0.5,
        )
        found = [
            {
                **indexed[result.id],
                "headings": result.headings,
                "page_numbers": result.page_numbers,
            }
            for result in results
            if result.id in indexed
        ]
        return found or retrieve(current, query, limit)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "rag_retrieval_unavailable fallback=approved_snapshot"
        )
        return retrieve(current, query, limit)
