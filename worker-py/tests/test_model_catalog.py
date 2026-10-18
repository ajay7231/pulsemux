import unittest
from unittest.mock import AsyncMock, patch
import httpx
from platform_support import platform_client, create_agent


class ModelCatalogTests(unittest.TestCase):
    def connection(self, client, provider="groq"):
        return client.post(
            "/api/connections",
            json={
                "name": "Test model account",
                "provider": provider,
                "credentials": {"api_key": "private-test-key"},
            },
        ).json()["id"]

    def test_catalog_uses_saved_key_and_filters_non_chat_models(self):
        with platform_client() as client:
            connection = self.connection(client)
            response = httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "llama-test"},
                        {"id": "whisper-large-v3"},
                        {"id": "meta-llama/llama-guard-4"},
                        {"id": "llama-inactive", "active": False},
                    ]
                },
            )
            with patch(
                "app.platform.model_catalog.httpx.AsyncClient.get",
                new=AsyncMock(return_value=response),
            ) as get:
                result = client.get(f"/api/connections/{connection}/models")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(
                result.json()["models"], [{"id": "llama-test", "name": "llama-test"}]
            )
            self.assertNotIn("private-test-key", result.text)
            self.assertEqual(
                get.call_args.kwargs["headers"]["Authorization"],
                "Bearer private-test-key",
            )
            client.post(f"/api/connections/{connection}/revoke")
            self.assertEqual(
                client.get(f"/api/connections/{connection}/models").status_code, 409
            )

    def test_provider_failure_is_actionable_and_does_not_echo_credentials(self):
        with platform_client() as client:
            connection = self.connection(client, "openai")
            with patch(
                "app.platform.model_catalog.httpx.AsyncClient.get",
                new=AsyncMock(
                    return_value=httpx.Response(401, text="private-test-key")
                ),
            ):
                result = client.get(f"/api/connections/{connection}/models")
            self.assertEqual(result.status_code, 422)
            self.assertIn("permissions", result.text)
            self.assertNotIn("private-test-key", result.text)
            client.post("/api/logout")
            self.assertEqual(
                client.get(f"/api/connections/{connection}/models").status_code, 401
            )

    def test_openai_catalog_excludes_unsupported_audio_and_reasoning_models(self):
        from app.platform.model_catalog import supported_chat_model

        self.assertTrue(supported_chat_model("openai", "gpt-4.1-mini"))
        for model in (
            "gpt-4o-realtime-preview",
            "gpt-4o-mini-tts",
            "gpt-5",
            "text-embedding-3-small",
        ):
            self.assertFalse(supported_chat_model("openai", model))

    def test_agent_preflight_rejects_model_removed_from_account(self):
        with platform_client() as client:
            agent = create_agent(client)
            with patch(
                "app.platform.model_catalog.list_chat_models",
                new=AsyncMock(return_value=[]),
            ):
                result = client.post(f"/api/agents/{agent['id']}/validate")
                self.assertEqual(result.status_code, 422)
                self.assertIn("unavailable", result.text)
            with patch(
                "app.platform.model_catalog.list_chat_models",
                new=AsyncMock(return_value=[agent["config"]["llm_model"]]),
            ):
                self.assertEqual(
                    client.post(f"/api/agents/{agent['id']}/validate").json(),
                    {"ready": True},
                )
