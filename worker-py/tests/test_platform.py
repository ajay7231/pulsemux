import asyncio
import json
import time
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select
from platform_support import platform_client, create_agent
from app.web_server import app, VoiceSession
from app.platform.database import database
from app.platform.models import *
from app.platform.security import encrypt, decrypt, password_hash
from app.platform.service import knowledge_hash


class PlatformTests(unittest.TestCase):
    def test_timezone_catalog_is_available_before_login(self):
        from zoneinfo import ZoneInfo

        with platform_client() as client:
            client.post("/api/logout")
            response = client.get("/api/timezones")
            self.assertEqual(response.status_code, 200)
            zones = response.json()
            self.assertEqual(zones, sorted(set(zones)))
            self.assertGreater(len(zones), 400)
            for expected in [
                "UTC",
                "Asia/Kolkata",
                "America/New_York",
                "Europe/London",
            ]:
                self.assertIn(expected, zones)
            for zone in zones:
                ZoneInfo(zone)

    def test_setup_login_encryption_and_logout(self):
        with platform_client() as client:
            self.assertFalse(client.get("/api/bootstrap").json()["setup_required"])
            self.assertEqual(
                client.post(
                    "/api/setup",
                    json={
                        "workspace": "Other",
                        "name": "Other",
                        "email": "other@example.test",
                        "password": "long-test-password",
                    },
                ).status_code,
                409,
            )
            result = client.post(
                "/api/connections",
                json={
                    "name": "Private Groq",
                    "provider": "groq",
                    "credentials": {"api_key": "never-return-this-key"},
                },
            )
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("never-return-this-key", result.text)
            self.assertNotIn("encrypted_secret", result.text)
            with database().Session() as db:
                row = db.get(Connection, result.json()["id"])
                self.assertNotIn("never-return-this-key", row.encrypted_secret)
                self.assertEqual(
                    decrypt(row.encrypted_secret)["api_key"], "never-return-this-key"
                )
            self.assertNotIn(
                "never-return-this-key", client.get("/api/connections").text
            )
            self.assertEqual(client.post("/api/logout").status_code, 200)
            self.assertEqual(client.get("/api/agents").status_code, 401)
            self.assertEqual(
                client.post(
                    "/api/login",
                    json={"email": "admin@example.test", "password": "bad"},
                ).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/api/login",
                    json={
                        "email": "admin@example.test",
                        "password": "a-test-password-123",
                    },
                ).status_code,
                200,
            )

    def test_csrf_and_viewer_cannot_modify_or_start_voice(self):
        with platform_client() as client:
            self.assertEqual(
                client.post(
                    "/api/collections",
                    json={"name": "Unsafe"},
                    headers={"origin": "https://evil.example"},
                ).status_code,
                403,
            )
            client.post(
                "/api/users",
                json={
                    "name": "Read Only",
                    "email": "viewer@example.test",
                    "password": "viewer-password-123",
                    "role": "viewer",
                },
            )
            client.post("/api/logout")
            client.post(
                "/api/login",
                json={
                    "email": "viewer@example.test",
                    "password": "viewer-password-123",
                },
            )
            self.assertEqual(client.get("/api/agents").status_code, 200)
            self.assertEqual(
                client.post("/api/collections", json={"name": "No access"}).status_code,
                403,
            )
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/ws/voice"):
                    pass

    def test_cross_workspace_records_and_credentials_are_not_accessible(self):
        with platform_client() as client:
            agent = create_agent(client)
            with database().Session() as db:
                other = Workspace(name="Other hospital")
                db.add(other)
                db.flush()
                user = User(
                    workspace_id=other.id,
                    name="Other",
                    email="other@example.test",
                    password_hash=password_hash("other-password-123"),
                )
                db.add(user)
                db.commit()
            client.post("/api/logout")
            client.post(
                "/api/login",
                json={"email": "other@example.test", "password": "other-password-123"},
            )
            self.assertEqual(client.get("/api/agents").json(), [])
            self.assertEqual(client.get("/api/connections").json(), [])
            self.assertEqual(client.get("/api/agents/" + agent["id"]).status_code, 404)
            self.assertEqual(
                client.post(
                    "/api/agents",
                    json={"name": "Wrong workspace", "config": agent["config"]},
                ).status_code,
                404,
            )

    def test_publishing_requires_test_and_preserves_versions(self):
        with platform_client() as client:
            agent = create_agent(client)
            self.assertEqual(
                client.post(f'/api/agents/{agent["id"]}/publish').status_code, 409
            )
            with database().Session() as db:
                row = db.get(Agent, agent["id"])
                row.tested_revision = row.revision
                row.tested_knowledge_hash = knowledge_hash([])
                db.commit()
            published = client.post(f'/api/agents/{agent["id"]}/publish')
            self.assertEqual(published.status_code, 200, published.text)
            version_id = published.json()["published_version_id"]
            update = {
                k: agent[k] for k in ["name", "description", "config", "revision"]
            }
            update["config"]["greeting"] = "A changed greeting for future callers."
            self.assertEqual(
                client.put("/api/agents/" + agent["id"], json=update).status_code, 200
            )
            self.assertEqual(
                client.put("/api/agents/" + agent["id"], json=update).status_code, 409
            )
            with database().Session() as db:
                version = db.get(AgentVersion, version_id)
                self.assertNotEqual(
                    version.config["greeting"], update["config"]["greeting"]
                )
            self.assertEqual(
                client.post(f'/api/agents/{agent["id"]}/publish').status_code, 409
            )

    def test_knowledge_review_publication_and_archive_pause(self):
        with platform_client() as client:
            collection = client.post(
                "/api/collections", json={"name": "Hospital policies"}
            ).json()
            document = client.post(
                f'/api/collections/{collection["id"]}/documents',
                json={
                    "title": "Visiting hours",
                    "content": "Visitors are welcome between 10 AM and 5 PM every weekday.",
                },
            ).json()
            self.assertEqual(document["status"], "draft")
            agent = create_agent(client, collection_ids=[collection["id"]])
            with database().Session() as db:
                row = db.get(Agent, agent["id"])
                row.tested_revision = row.revision
                row.tested_knowledge_hash = knowledge_hash([])
                db.commit()
            client.post(f'/api/documents/{document["id"]}/approve')
            self.assertEqual(
                client.post(f'/api/agents/{agent["id"]}/publish').status_code, 409
            )
            from app.platform.service import knowledge_snapshot, retrieve

            with database().Session() as db:
                row = db.get(Agent, agent["id"])
                snapshot = knowledge_snapshot(db, row.workspace_id, [collection["id"]])
                row.tested_knowledge_hash = knowledge_hash(snapshot)
                db.commit()
                self.assertEqual(
                    retrieve(snapshot, "What are the visiting hours?")[0]["title"],
                    "Visiting hours",
                )
            self.assertEqual(
                client.post(f'/api/agents/{agent["id"]}/publish').status_code, 200
            )
            client.post(f'/api/documents/{document["id"]}/archive')
            self.assertEqual(
                client.get("/api/agents/" + agent["id"]).json()["status"], "paused"
            )

    def test_managed_simulation_persists_transcripts_and_uses_saved_credentials(self):
        async def synthesize(session, clause, turn_id=None):
            return None

        async def transcribe(session, audio, mime):
            return "Hello"

        with platform_client() as client, patch.object(
            VoiceSession, "synthesize_audio", synthesize
        ):
            agent = create_agent(client)
            # An explicit callback exercises a real permission-checked action
            # without issuing a paid LLM request.
            with client.websocket_connect(
                "/ws/voice", headers={"origin": "http://testserver"}
            ) as ws:
                self.assertEqual(ws.receive_json()["type"], "connected")
                ws.send_json(
                    {
                        "event": "start",
                        "agent_id": agent["id"],
                        "draft": True,
                        "turn_id": "greet",
                    }
                )
                started = ws.receive_json()
                self.assertEqual(started["type"], "call_started")
                call_id = started["call_id"]
                while ws.receive_json()["type"] != "turn_complete":
                    pass
                ws.send_json(
                    {
                        "type": "user_text",
                        "text": "Call me back please",
                        "turn_id": "caller",
                    }
                )
                messages = []
                while True:
                    message = ws.receive_json()
                    messages.append(message)
                    if message["type"] == "turn_complete":
                        break
                self.assertEqual(messages[-1]["turn_id"], "caller")
                ws.send_json({"event": "stop"})
                self.assertEqual(ws.receive_json()["type"], "call_ended")
            detail = client.get("/api/calls/" + call_id).json()
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(detail["outcome"], "callback_requested")
            self.assertTrue(
                any(
                    e["kind"] == "transcript" and e["payload"]["speaker"] == "PATIENT"
                    for e in detail["events"]
                )
            )
            self.assertEqual(len(client.get("/api/tasks").json()), 1)
            self.assertEqual(
                client.get("/api/agents/" + agent["id"]).json()["tested_revision"],
                agent["revision"],
            )
            with database().Session() as db:
                from app.platform.runtime import session_class
                from unittest.mock import Mock

                managed = session_class()(Mock(), call_id)
                self.assertEqual(
                    managed.provider_key("llm", "GROQ_API_KEY"), "fake-groq-key"
                )
                self.assertIsNone(managed.provider_key("tts", "DEEPGRAM_API_KEY"))

    def test_unauthenticated_voice_rejected(self):
        with platform_client() as client:
            client.post("/api/logout")
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/ws/voice"):
                    pass

    def test_csv_import_requires_preview_validation_and_defaults_to_no_consent(self):
        with platform_client() as client:
            preview = client.post(
                "/api/contacts/import-preview",
                files={
                    "file": (
                        "contacts.csv",
                        b"name,phone,appointment_date\nSynthetic Patient,+15551234567,20 October\n",
                        "text/csv",
                    )
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            data = preview.json()
            self.assertFalse(data["contacts"][0]["consent"])
            self.assertEqual(
                data["contacts"][0]["variables"]["appointment_date"], "20 October"
            )
            self.assertEqual(client.get("/api/contacts").json(), [])
            result = client.post("/api/contacts/import", json=data["contacts"])
            self.assertEqual(result.json()["imported"], 1)
            self.assertEqual(
                client.post("/api/contacts/import", json=data["contacts"]).json()[
                    "duplicates"
                ],
                1,
            )
            invalid = client.post(
                "/api/contacts/import-preview",
                files={
                    "file": (
                        "bad.csv",
                        b"name,phone\nInvalid,not-a-number\n",
                        "text/csv",
                    )
                },
            ).json()
            self.assertEqual(len(invalid["errors"]), 1)

    def test_no_outbound_call_without_consent_or_public_origin(self):
        with platform_client() as client:
            agent = create_agent(client)
            response = client.post(
                "/api/calls/outbound",
                json={
                    "agent_id": agent["id"],
                    "phone_number_id": "missing",
                    "contact_id": "missing",
                },
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("PUBLIC_BASE_URL", response.text)
