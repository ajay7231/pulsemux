import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app.platform.database import database
from app.web_server import app


@contextmanager
def platform_client():
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {
            "DATABASE_URL": f"sqlite:///{directory}/test.db",
            "PLATFORM_DATA_DIR": directory,
            "PLATFORM_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
            "PLATFORM_ENV": "development",
            "PUBLIC_BASE_URL": "",
        },
    ):
        database.cache_clear()
        with TestClient(app) as client:
            response = client.post(
                "/api/setup",
                json={
                    "workspace": "Test Hospital",
                    "name": "Test Admin",
                    "email": "admin@example.test",
                    "password": "a-test-password-123",
                    "timezone": "Asia/Kolkata",
                },
            )
            assert response.status_code == 200, response.text
            yield client
        database().engine.dispose()
        database.cache_clear()


def create_agent(client, **changes):
    groq = client.post(
        "/api/connections",
        json={
            "name": "Test Groq",
            "provider": "groq",
            "credentials": {"api_key": "fake-groq-key"},
        },
    ).json()
    deepgram = client.post(
        "/api/connections",
        json={
            "name": "Test Deepgram",
            "provider": "deepgram",
            "credentials": {"api_key": "fake-deepgram-key"},
        },
    ).json()
    from app.platform.schemas import AgentConfig

    config = AgentConfig(
        stt_connection_id=deepgram["id"], llm_connection_id=groq["id"]
    ).model_dump()
    config.update(changes)
    if config["tts_engine"] == "deepgram":
        config["tts_connection_id"] = deepgram["id"]
    if config["stt_engine"] == "groq":
        config["stt_connection_id"] = groq["id"]
    response = client.post(
        "/api/agents", json={"name": "Reception test agent", "config": config}
    )
    assert response.status_code == 200, response.text
    return response.json()
