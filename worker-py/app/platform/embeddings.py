"""Optional OpenAI embeddings; lexical retrieval works without a paid provider."""

import httpx
import numpy as np
from fastapi import HTTPException
from .database import database
from .models import Connection
from .service import owned, retrieve
from .security import decrypt

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


async def embed(workspace_id, connection_id, texts):
    with database().Session() as db:
        connection = owned(db, Connection, connection_id, workspace_id)
        if connection.provider != "openai" or not connection.active:
            raise HTTPException(
                409, "Choose an active OpenAI connection for embeddings"
            )
        key = decrypt(connection.encrypted_secret)["api_key"]
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": MODEL, "input": texts, "dimensions": DIMENSIONS},
            )
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda row: row["index"])
        vectors = [row["embedding"] for row in data]
        if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
            raise ValueError("Invalid embeddings")
        return vectors
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(
            502,
            "Embedding provider failed. Check the connection and available credit; lexical search remains available.",
        )


async def retrieve_hybrid(workspace_id, snapshot, query, limit=4):
    lexical = retrieve(snapshot, query, limit=12)
    semantic = []
    providers = {
        c.get("embedding_connection_id") for c in snapshot if c.get("embedding")
    }
    for connection_id in providers:
        if not connection_id:
            continue
        try:
            vector = np.asarray(
                (await embed(workspace_id, connection_id, [query]))[0], dtype=float
            )
        except HTTPException:
            continue
        scored = []
        for chunk in snapshot:
            if chunk.get("embedding_connection_id") != connection_id or not chunk.get(
                "embedding"
            ):
                continue
            import time

            if chunk.get("expires_at") and chunk["expires_at"] <= time.time():
                continue
            stored = np.asarray(chunk["embedding"], dtype=float)
            score = float(
                np.dot(vector, stored)
                / (np.linalg.norm(vector) * np.linalg.norm(stored) + 1e-12)
            )
            if score >= 0.25:
                scored.append((score, chunk))
        semantic.extend(
            c for _, c in sorted(scored, key=lambda row: row[0], reverse=True)[:12]
        )
    # Reciprocal-rank fusion keeps exact department names useful alongside semantics.
    scores = {}
    chunks = {}
    for ranking in [lexical, semantic]:
        for rank, chunk in enumerate(ranking):
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1 / (60 + rank)
            chunks[chunk["id"]] = chunk
    return [chunks[key] for key in sorted(scores, key=scores.get, reverse=True)[:limit]]
