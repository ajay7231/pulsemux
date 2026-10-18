"""Warm local embeddings and one-roundtrip dense/BM25 reciprocal-rank fusion."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cached_property
from uuid import NAMESPACE_URL, uuid5

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import AsyncQdrantClient, models

from .parser import ClinicalChunk, ClinicalDocumentProcessor, DENSE_MODEL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    score: float
    protocol_name: str
    headings: list[str]
    page_numbers: list[int]
    raw_text: str
    enriched_text: str

    @cached_property
    def formatted_text(self) -> str:
        section = " > ".join(self.headings) or "General"
        pages = ", ".join(map(str, self.page_numbers)) or "not available"
        return f"[Protocol: {self.protocol_name} | Section: {section} | Pages: {pages}]\n{self.raw_text}"


class ClinicalKnowledgeBase:
    def __init__(
        self,
        url: str | None = None,
        *,
        collection_name: str = "clinical_protocols",
        cache_dir: str = "./model_cache",
        workspace_id: str | None = None,
        api_key: str | None = None,
    ):
        self.collection_name = collection_name
        self.workspace_id = workspace_id
        self.client = AsyncQdrantClient(
            url=url or os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=api_key or os.getenv("QDRANT_API_KEY"),
            prefer_grpc=True,
            timeout=10,
        )
        self.dense = TextEmbedding(
            model_name=DENSE_MODEL,
            cache_dir=cache_dir,
            threads=int(os.getenv("RAG_ONNX_THREADS", "1")),
        )
        self.sparse = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=cache_dir)
        # embed() is lazy. Materialize both generators to actually warm the runtimes.
        list(self.dense.embed(["warmup"]))
        list(self.sparse.embed(["warmup"]))
        self.cache_dir = cache_dir
        self._processor = None
        self._ingest_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="rag-ingest"
        )
        self._query_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="rag-query"
        )
        self._ingest_lock = asyncio.Lock()
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self.last_retrieval_ms = 0.0

    @property
    def processor(self) -> ClinicalDocumentProcessor:
        # Parsing/layout models never initialize in the live retrieval path.
        if self._processor is None:
            self._processor = ClinicalDocumentProcessor(cache_dir=self.cache_dir)
        return self._processor

    async def init_collection(self):
        async with self._init_lock:
            if self._initialized:
                return
            if not await self.client.collection_exists(self.collection_name):
                try:
                    await self.client.create_collection(
                        self.collection_name,
                        vectors_config={
                            "dense": models.VectorParams(
                                size=384, distance=models.Distance.COSINE
                            )
                        },
                        sparse_vectors_config={
                            "sparse": models.SparseVectorParams(
                                modifier=models.Modifier.IDF
                            )
                        },
                    )
                except Exception:
                    # HTTP 409 and gRPC ALREADY_EXISTS both occur during concurrent startup.
                    if not await self.client.collection_exists(self.collection_name):
                        raise
            info = await self.client.get_collection(self.collection_name)
            dense = info.config.params.vectors
            sparse = info.config.params.sparse_vectors or {}
            if (
                not isinstance(dense, dict)
                or "dense" not in dense
                or dense["dense"].size != 384
                or dense["dense"].distance != models.Distance.COSINE
                or "sparse" not in sparse
                or sparse["sparse"].modifier != models.Modifier.IDF
            ):
                raise ValueError(
                    "Qdrant collection has an incompatible embedding schema"
                )
            for key in ("protocol_name", "workspace_id", "document_id"):
                await self.client.create_payload_index(
                    self.collection_name,
                    key,
                    models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            self._initialized = True

    def point_id(self, chunk: ClinicalChunk, document_id: str | None = None) -> str:
        # Default API follows protocol+enriched UUID5; hospital usage isolates documents and tenants.
        namespace = (
            NAMESPACE_URL
            if not (self.workspace_id or document_id)
            else uuid5(NAMESPACE_URL, f"{self.workspace_id or ''}\0{document_id or ''}")
        )
        return str(uuid5(namespace, chunk.protocol_name + "\0" + chunk.enriched_text))

    async def ingest_document(
        self,
        file_path: str,
        protocol_name: str,
        *,
        document_id: str | None = None,
        batch_size: int = 32,
    ) -> int:
        loop = asyncio.get_running_loop()
        chunks = await loop.run_in_executor(
            self._ingest_pool,
            lambda: self.processor.process_document(file_path, protocol_name),
        )
        return await self.ingest_chunks(
            chunks, document_id=document_id, batch_size=batch_size
        )

    async def ingest_chunks(
        self,
        chunks: list[ClinicalChunk],
        *,
        document_id: str | None = None,
        batch_size: int = 32,
    ) -> int:
        if not chunks or not 1 <= batch_size <= 128:
            raise ValueError("Provide nonempty chunks and a batch size from 1 to 128")
        await self.init_collection()
        loop = asyncio.get_running_loop()
        async with self._ingest_lock:
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]

                def embed_batch():
                    texts = [chunk.enriched_text for chunk in batch]
                    # Independently verify callers did not bypass parser token validation.
                    if any(self.processor.token_count(text) > 512 for text in texts):
                        raise ValueError("Embedding input exceeds 512 tokens")
                    return list(self.dense.embed(texts, batch_size=batch_size)), list(
                        self.sparse.embed(texts, batch_size=batch_size)
                    )

                dense, sparse = await loop.run_in_executor(
                    self._ingest_pool, embed_batch
                )
                points = [
                    models.PointStruct(
                        id=self.point_id(chunk, document_id),
                        vector={
                            "dense": d.tolist(),
                            "sparse": models.SparseVector(
                                indices=s.indices.tolist(), values=s.values.tolist()
                            ),
                        },
                        payload={
                            **chunk.model_dump(),
                            "workspace_id": self.workspace_id or "",
                            "document_id": document_id or "",
                        },
                    )
                    for chunk, d, s in zip(batch, dense, sparse, strict=True)
                ]
                await self.client.upsert(self.collection_name, points, wait=True)
        return len(chunks)

    def _query_vectors(self, query):
        dense = next(self.dense.query_embed(query)).tolist()
        sparse = next(self.sparse.query_embed(query))
        return dense, models.SparseVector(
            indices=sparse.indices.tolist(), values=sparse.values.tolist()
        )

    async def retrieve(
        self,
        query: str,
        protocol_name: str | None = None,
        top_k: int = 3,
        *,
        allowed_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip() or len(query) > 8000 or not 1 <= top_k <= 10:
            raise ValueError(
                "Provide a query up to 8,000 characters and top_k from 1 to 10"
            )
        if allowed_ids == []:
            chunks = []
        if not self._initialized:
            raise RuntimeError(
                "Call init_collection during startup, before serving live retrieval"
            )
        started = time.perf_counter()
        dense, sparse = await asyncio.get_running_loop().run_in_executor(
            self._query_pool, self._query_vectors, query
        )
        conditions = []
        if self.workspace_id is not None:
            conditions.append(
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=self.workspace_id)
                )
            )
        if protocol_name is not None:
            conditions.append(
                models.FieldCondition(
                    key="protocol_name", match=models.MatchValue(value=protocol_name)
                )
            )
        if allowed_ids is not None:
            conditions.append(models.HasIdCondition(has_id=allowed_ids))
        scope = models.Filter(must=conditions) if conditions else None
        result = await self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(query=dense, using="dense", limit=10, filter=scope),
                models.Prefetch(query=sparse, using="sparse", limit=10, filter=scope),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=scope,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        return [
            RetrievedChunk(
                id=str(point.id),
                score=point.score,
                **{
                    key: (point.payload or {})[key]
                    for key in (
                        "protocol_name",
                        "headings",
                        "page_numbers",
                        "raw_text",
                        "enriched_text",
                    )
                },
            )
            for point in result.points
        ]

        for chunk in chunks:
            _ = chunk.formatted_text
        self.last_retrieval_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "rag_retrieval duration_ms=%.3f results=%d",
            self.last_retrieval_ms,
            len(result.points),
        )
        return chunks

    async def close(self):
        await self.client.close()
        self._query_pool.shutdown(wait=True, cancel_futures=True)
        self._ingest_pool.shutdown(wait=True, cancel_futures=True)
