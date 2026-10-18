import asyncio
import unittest
from unittest.mock import patch
import httpx
from platform_support import platform_client
from app.platform.database import database
from app.platform.models import Chunk
from app.platform.embeddings import retrieve_hybrid

RealClient = httpx.AsyncClient


class EmbeddingTests(unittest.TestCase):
    def test_explicit_indexing_persists_vectors_and_enables_semantic_retrieval(self):
        with platform_client() as client:
            connection = client.post(
                "/api/connections",
                json={
                    "name": "OpenAI embeddings",
                    "provider": "openai",
                    "credentials": {"api_key": "test-only-key"},
                },
            ).json()
            collection = client.post(
                "/api/collections",
                json={
                    "name": "Clinic knowledge",
                    "embedding_connection_id": connection["id"],
                },
            ).json()
            document = client.post(
                f'/api/collections/{collection["id"]}/documents',
                json={
                    "title": "Parking",
                    "content": "Complimentary underground car parking is available at the north entrance.",
                },
            ).json()
            vector = [1.0] + [0.0] * 1535

            def respond(request):
                self.assertEqual(request.url.path, "/v1/embeddings")
                return httpx.Response(
                    200, json={"data": [{"index": 0, "embedding": vector}]}
                )

            with patch(
                "app.platform.embeddings.httpx.AsyncClient",
                side_effect=lambda **kw: RealClient(
                    transport=httpx.MockTransport(respond), **kw
                ),
            ):
                result = client.post(f'/api/documents/{document["id"]}/index')
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["indexed_chunks"], 1)
                with database().Session() as db:
                    chunk = db.query(Chunk).one()
                    self.assertEqual(len(chunk.embedding), 1536)
                    snapshot = [
                        {
                            "id": chunk.id,
                            "content": chunk.content,
                            "title": "Parking",
                            "embedding": chunk.embedding,
                            "embedding_connection_id": connection["id"],
                            "expires_at": None,
                        }
                    ]
                    workspace_id = chunk.workspace_id
                matches = asyncio.run(
                    retrieve_hybrid(
                        workspace_id, snapshot, "Where can I leave my automobile?"
                    )
                )
                self.assertEqual(matches[0]["title"], "Parking")

    def test_embedding_failure_leaves_keyword_retrieval_available(self):
        snapshot = [
            {
                "id": "one",
                "title": "Opening hours",
                "content": "Reception opening hours are 9 AM to 5 PM",
                "embedding": [1.0] * 1536,
                "embedding_connection_id": "missing",
                "expires_at": None,
            }
        ]
        with platform_client():
            result = asyncio.run(retrieve_hybrid("missing", snapshot, "Opening hours"))
        self.assertEqual(result[0]["id"], "one")
