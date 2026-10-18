import asyncio
import base64
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
import httpx
from twilio.request_validator import RequestValidator
from platform_support import platform_client, create_agent
from app.platform.database import database
from app.platform.models import Agent, Call, AgentVersion, Recipient, Campaign, Contact
from app.platform.service import knowledge_hash
from app.platform.telephony import PhoneTransport, wav_mulaw
from app.pipeline.call_audio import mulaw_wav

RealClient = httpx.AsyncClient
SID = "AC" + "1" * 32
CALLSID = "CA" + "2" * 32
TOKEN = "test-auth-token-only"
BASE = "https://hospital.example"


class TelephonyTests(unittest.TestCase):
    def seed(self, client):
        agent = create_agent(client)
        with database().Session() as db:
            row = db.get(Agent, agent["id"])
            row.tested_revision = row.revision
            row.tested_knowledge_hash = knowledge_hash([])
            db.commit()
        published = client.post(f'/api/agents/{agent["id"]}/publish').json()
        connection = client.post(
            "/api/connections",
            json={
                "name": "Test Twilio",
                "provider": "twilio",
                "credentials": {"account_sid": SID, "auth_token": TOKEN},
            },
        ).json()
        number = client.post(
            "/api/numbers",
            json={
                "number": "+15551234567",
                "connection_id": connection["id"],
                "agent_id": agent["id"],
            },
        ).json()
        contact = client.post(
            "/api/contacts",
            json={
                "name": "Synthetic Patient",
                "phone": "+15557654321",
                "consent": True,
                "timezone": "UTC",
                "variables": {},
            },
        ).json()
        return agent, connection, number, contact

    def test_outbound_is_durable_and_uses_twilio_account_then_signed_callbacks(self):
        with platform_client() as client:
            agent, connection, number, contact = self.seed(client)
            requests = []

            def handler(request):
                requests.append(request)
                self.assertTrue(request.url.path.endswith("/Calls.json"))
                body = parse_qs(request.content.decode())
                self.assertIn("<Connect>", body["Twiml"][0])
                self.assertIn("/ws/telephony/", body["Twiml"][0])
                self.assertEqual(body["To"], [contact["phone"]])
                # The durable call intent exists before an external side effect.
                with database().Session() as db:
                    self.assertEqual(len(db.query(Call).all()), 1)
                return httpx.Response(201, json={"sid": CALLSID, "status": "queued"})

            with patch.dict(os.environ, {"PUBLIC_BASE_URL": BASE}), patch(
                "app.platform.telephony.httpx.AsyncClient",
                side_effect=lambda **kw: RealClient(
                    transport=httpx.MockTransport(handler), **kw
                ),
            ):
                response = client.post(
                    "/api/calls/outbound",
                    json={
                        "agent_id": agent["id"],
                        "phone_number_id": number["id"],
                        "contact_id": contact["id"],
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                call = response.json()
                path = f'/api/twilio/{connection["id"]}/status/{call["id"]}'
                form = {
                    "AccountSid": SID,
                    "CallSid": CALLSID,
                    "CallStatus": "completed",
                }
                self.assertEqual(client.post(path, data=form).status_code, 403)
                signature = RequestValidator(TOKEN).compute_signature(BASE + path, form)
                result = client.post(
                    path, data=form, headers={"x-twilio-signature": signature}
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(
                    client.get("/api/calls/" + call["id"]).json()["status"], "completed"
                )
                # Duplicate or out-of-order callbacks cannot revive a completed call.
                form["CallStatus"] = "ringing"
                signature = RequestValidator(TOKEN).compute_signature(BASE + path, form)
                client.post(path, data=form, headers={"x-twilio-signature": signature})
                self.assertEqual(
                    client.get("/api/calls/" + call["id"]).json()["status"], "completed"
                )
            self.assertEqual(len(requests), 1)

    def test_unconsented_contact_never_reaches_provider(self):
        with platform_client() as client:
            agent, connection, number, contact = self.seed(client)
            contact["consent"] = False
            client.put(
                "/api/contacts/" + contact["id"],
                json={
                    k: contact[k]
                    for k in [
                        "name",
                        "phone",
                        "consent",
                        "opted_out",
                        "timezone",
                        "variables",
                    ]
                },
            )
            with patch.dict(os.environ, {"PUBLIC_BASE_URL": BASE}), patch(
                "app.platform.telephony.httpx.AsyncClient"
            ) as provider:
                response = client.post(
                    "/api/calls/outbound",
                    json={
                        "agent_id": agent["id"],
                        "phone_number_id": number["id"],
                        "contact_id": contact["id"],
                    },
                )
                self.assertEqual(response.status_code, 409)
                provider.assert_not_called()

    def test_timeout_is_uncertain_and_does_not_automatically_redial(self):
        with platform_client() as client:
            agent, connection, number, contact = self.seed(client)

            def timeout(request):
                raise httpx.ReadTimeout("test timeout", request=request)

            with patch.dict(os.environ, {"PUBLIC_BASE_URL": BASE}), patch(
                "app.platform.telephony.httpx.AsyncClient",
                side_effect=lambda **kw: RealClient(
                    transport=httpx.MockTransport(timeout), **kw
                ),
            ):
                result = client.post(
                    "/api/calls/outbound",
                    json={
                        "agent_id": agent["id"],
                        "phone_number_id": number["id"],
                        "contact_id": contact["id"],
                    },
                )
            self.assertEqual(result.json()["status"], "dispatch_unknown")
            self.assertEqual(len(client.get("/api/tasks").json()), 1)

    def test_signed_inbound_routes_to_assigned_agent(self):
        with platform_client() as client:
            agent, connection, number, contact = self.seed(client)
            path = f'/api/twilio/{connection["id"]}/inbound'
            form = {
                "AccountSid": SID,
                "CallSid": CALLSID,
                "To": number["number"],
                "From": contact["phone"],
            }
            with patch.dict(os.environ, {"PUBLIC_BASE_URL": BASE}):
                self.assertEqual(client.post(path, data=form).status_code, 403)
                signature = RequestValidator(TOKEN).compute_signature(BASE + path, form)
                result = client.post(
                    path, data=form, headers={"x-twilio-signature": signature}
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertIn("wss://hospital.example/ws/telephony/", result.text)
                self.assertIn("<Hangup", result.text)
                self.assertEqual(
                    client.get("/api/calls").json()[0]["direction"], "inbound"
                )

    def test_campaign_dispatch_is_once_and_respects_pause(self):
        from app.platform.jobs import dispatch_due

        with platform_client() as client:
            agent, connection, number, contact = self.seed(client)
            campaign = client.post(
                "/api/campaigns",
                json={
                    "name": "Synthetic reminder campaign",
                    "agent_id": agent["id"],
                    "phone_number_id": number["id"],
                    "contact_ids": [contact["id"]],
                    "starts_at": time.time() - 5,
                    "window_start": 0,
                    "window_end": 24,
                },
            ).json()
            counter = []

            def success(request):
                counter.append(request)
                return httpx.Response(201, json={"sid": CALLSID, "status": "queued"})

            with patch.dict(os.environ, {"PUBLIC_BASE_URL": BASE}), patch(
                "app.platform.telephony.httpx.AsyncClient",
                side_effect=lambda **kw: RealClient(
                    transport=httpx.MockTransport(success), **kw
                ),
            ):
                client.post(f'/api/campaigns/{campaign["id"]}/start')
                asyncio.run(dispatch_due())
                asyncio.run(dispatch_due())
                self.assertEqual(len(counter), 1)
                client.post(f'/api/campaigns/{campaign["id"]}/pause')
                asyncio.run(dispatch_due())
                self.assertEqual(len(counter), 1)
            with database().Session() as db:
                recipient = db.query(Recipient).one()
                self.assertEqual(recipient.attempts, 1)
                self.assertEqual(recipient.status, "dispatching")

    def test_telephony_encoder_uses_standard_mulaw_polarity(self):
        self.assertEqual(
            wav_mulaw(base64.b64encode(mulaw_wav(bytes([255, 128, 0]))).decode()),
            bytes([255, 128, 0]),
        )

    def test_goodbye_hangup_waits_for_twilio_playback_mark(self):
        class Socket:
            async def send_json(self, value):
                pass

        async def scenario():
            transport = PhoneTransport(Socket(), "stream", "call")
            transport.session = type("Session", (), {"transfer_requested": False})()
            from unittest.mock import AsyncMock

            with patch(
                "app.platform.telephony.update_twilio_call", new_callable=AsyncMock
            ) as hangup:
                await transport.send_text(
                    json.dumps(
                        {
                            "type": "turn_complete",
                            "turn_id": "goodbye",
                            "end_call": True,
                        }
                    )
                )
                hangup.assert_not_called()
                await transport.mark("unrelated")
                hangup.assert_not_called()
                await transport.mark("goodbye")
                hangup.assert_awaited_once_with("call")

        asyncio.run(scenario())
