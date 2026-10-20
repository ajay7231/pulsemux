"""Signed Twilio webhooks, durable outbound dispatch, and shared voice transport."""

import asyncio
import base64
import io
import json
import os
import secrets
import time
import wave
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring
import numpy as np
import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, update
from twilio.request_validator import RequestValidator
from .database import database
from .models import (
    Connection,
    PhoneNumber,
    Agent,
    AgentVersion,
    Contact,
    Call,
    Recipient,
    Campaign,
    StaffTask,
    Workspace,
)
from .service import owned, event, validate_config, validate_snapshot
from .security import decrypt, digest

router = APIRouter()
TERMINAL = {"completed", "busy", "failed", "no-answer", "canceled"}


def public_base():
    value = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.query
        or parts.fragment
        or parts.path
    ):
        raise HTTPException(
            422,
            "Set PUBLIC_BASE_URL to your public HTTPS origin before enabling telephone calls",
        )
    return value


def twilio_credentials(db, connection_id, workspace_id):
    connection = owned(db, Connection, connection_id, workspace_id)
    if connection.provider != "twilio" or not connection.active:
        raise HTTPException(409, "Twilio connection is unavailable")
    return decrypt(connection.encrypted_secret)


def twilio_auth(credentials):
    return (
        credentials.get("api_key_sid") or credentials["account_sid"],
        credentials.get("api_key_secret") or credentials["auth_token"],
    )


def stream_twiml(call, token):
    root = Element("Response")
    connect = SubElement(root, "Connect")
    stream = SubElement(
        connect,
        "Stream",
        url=public_base().replace("https://", "wss://", 1) + f"/ws/telephony/{call.id}",
    )
    SubElement(stream, "Parameter", name="token", value=token)
    SubElement(root, "Hangup")
    return tostring(root, encoding="unicode")


async def signed_form(request, credentials):
    form = await request.form()
    url = public_base() + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    if not RequestValidator(credentials["auth_token"]).validate(
        url, form, request.headers.get("x-twilio-signature", "")
    ):
        raise HTTPException(403, "Invalid Twilio signature")
    if form.get("AccountSid") != credentials["account_sid"]:
        raise HTTPException(403, "Account mismatch")
    return form


async def place_outbound(
    db,
    workspace_id,
    agent_id,
    number_id,
    contact_id,
    version_id=None,
    recipient_id=None,
):
    base = public_base()
    agent = owned(db, Agent, agent_id, workspace_id)
    if agent.status != "published":
        raise HTTPException(409, "Agent is not published")
    version = owned(
        db, AgentVersion, version_id or agent.published_version_id, workspace_id
    )
    if version.agent_id != agent.id:
        raise HTTPException(422, "Agent version mismatch")
    validate_config(db, workspace_id, version.config, True)
    validate_snapshot(db, workspace_id, version.knowledge)
    number = owned(db, PhoneNumber, number_id, workspace_id)
    contact = owned(db, Contact, contact_id, workspace_id)
    if not contact.consent or contact.opted_out:
        raise HTTPException(409, "This contact has not consented or has opted out")
    connection = owned(db, Connection, number.connection_id, workspace_id)
    if not connection.active or connection.provider not in {"twilio", "plivo"}:
        raise HTTPException(409, "Telephone connection is unavailable")
    credentials = decrypt(connection.encrypted_secret)
    provider = connection.provider
    token = secrets.token_urlsafe(32)
    config = dict(version.config)
    config["_has_contact"] = True
    call = Call(
        workspace_id=workspace_id,
        agent_id=agent.id,
        version_id=version.id,
        connection_id=number.connection_id,
        contact_id=contact.id,
        recipient_id=recipient_id,
        direction="outbound",
        to_number=contact.phone,
        from_number=number.number,
        config=config,
        knowledge=version.knowledge,
        variables={**contact.variables, "patient_name": contact.name},
        stream_token_hash=digest(token),
        status="dispatching",
        deadline=time.time() + config["max_duration_seconds"] + 90,
    )
    db.add(call)
    db.flush()
    if recipient_id:
        recipient = db.get(Recipient, recipient_id)
        recipient.last_call_id = call.id
    event(db, call, "dispatching", {})
    # Persist intent before contacting a provider. A timeout is ambiguous and never
    # retried automatically: callbacks/reconciliation decide what happened.
    db.commit()
    try:
        if provider == "plivo":
            from .plivo import dispatch_call
            response = await dispatch_call(call, credentials, token, base)
        else:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f'https://api.twilio.com/2010-04-01/Accounts/{credentials["account_sid"]}/Calls.json',
                    auth=twilio_auth(credentials),
                    data={
                        "To": contact.phone,
                        "From": number.number,
                        "Twiml": stream_twiml(call, token),
                        "StatusCallback": f"{base}/api/twilio/{number.connection_id}/status/{call.id}",
                        "StatusCallbackEvent": [
                            "initiated",
                            "ringing",
                            "answered",
                            "completed",
                        ],
                        "Timeout": "30",
                        "TimeLimit": str(config["max_duration_seconds"]),
                    },
                )
        db.refresh(call)
        if not response.is_success:
            call.status = "failed"
            call.error = f"{provider.title()} rejected the request (HTTP {response.status_code})"
            call.ended_at = time.time()
            finish_recipient(db, call, "failed")
        else:
            if provider == "plivo":
                from .plivo import record_dispatch
                record_dispatch(call, response.json())
            else:
                call.provider_sid = response.json()["sid"]
            if not call.ended_at and (provider == "twilio" or call.status in {"dispatching", "dispatch_unknown"}):
                call.status = response.json().get("status", "queued")
    except (httpx.RequestError, KeyError, ValueError):
        call.status = "dispatch_unknown"
        call.error = "Provider response was uncertain. Review the provider call log before retrying."
        db.add(
            StaffTask(
                workspace_id=workspace_id,
                call_id=call.id,
                title="Verify uncertain outbound dispatch",
                details="Do not redial until the provider call log has been checked.",
            )
        )
    db.commit()
    return call


def finish_recipient(db, call, status):
    if not call.recipient_id:
        return
    recipient = db.get(Recipient, call.recipient_id)
    if not recipient or recipient.last_call_id != call.id:
        return
    campaign = db.get(Campaign, recipient.campaign_id)
    contact = db.get(Contact, recipient.contact_id)
    if contact.opted_out or not contact.consent:
        recipient.status = "suppressed"
    elif (
        status in {"busy", "no-answer"}
        and recipient.attempts < campaign.config["max_attempts"]
        and campaign.status != "cancelled"
    ):
        recipient.status = "pending"
        recipient.next_attempt_at = time.time() + campaign.config["retry_minutes"] * 60
    else:
        recipient.status = "completed" if status == "completed" else "failed"


@router.post("/api/twilio/{connection_id}/inbound")
async def inbound(connection_id: str, request: Request):
    with database().Session() as db:
        connection = db.get(Connection, connection_id)
        if not connection or not connection.active or connection.provider != "twilio":
            raise HTTPException(404, "Connection not found")
        credentials = decrypt(connection.encrypted_secret)
        form = await signed_form(request, credentials)
        number = db.scalar(
            select(PhoneNumber).where(
                PhoneNumber.connection_id == connection_id,
                PhoneNumber.number == form.get("To"),
            )
        )
        if not number:
            raise HTTPException(404, "Number is not assigned")
        agent = db.get(Agent, number.agent_id)
        if agent.status != "published":
            return Response(
                "<Response><Say>The assistant is currently unavailable. Please contact the hospital directly.</Say><Hangup/></Response>",
                media_type="application/xml",
            )
        existing = db.scalar(
            select(Call).where(Call.provider_sid == form.get("CallSid"))
        )
        if existing:
            if existing.stream_claimed or existing.ended_at:
                return Response(
                    "<Response><Hangup/></Response>", media_type="application/xml"
                )
            token = secrets.token_urlsafe(32)
            existing.stream_token_hash = digest(token)
            xml = stream_twiml(existing, token)
            db.commit()
            return Response(xml, media_type="application/xml")
        version = db.get(AgentVersion, agent.published_version_id)
        validate_config(db, agent.workspace_id, version.config, True)
        validate_snapshot(db, agent.workspace_id, version.knowledge)
        token = secrets.token_urlsafe(32)
        contact = db.scalar(
            select(Contact).where(
                Contact.workspace_id == agent.workspace_id,
                Contact.phone == form.get("From"),
            )
        )
        config = dict(version.config)
        config["_has_contact"] = bool(contact)
        call = Call(
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            version_id=version.id,
            connection_id=connection_id,
            contact_id=contact.id if contact else None,
            direction="inbound",
            status="ringing",
            to_number=form.get("To"),
            from_number=form.get("From"),
            provider_sid=form.get("CallSid"),
            config=config,
            knowledge=version.knowledge,
            variables={"patient_name": contact.name} if contact else {},
            stream_token_hash=digest(token),
            deadline=time.time() + config["max_duration_seconds"],
        )
        db.add(call)
        db.flush()
        event(db, call, "inbound", {})
        xml = stream_twiml(call, token)
        db.commit()
        return Response(xml, media_type="application/xml")


@router.post("/api/twilio/{connection_id}/status/{call_id}")
async def status_callback(connection_id: str, call_id: str, request: Request):
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.connection_id != connection_id:
            raise HTTPException(404, "Call not found")
        credentials = twilio_credentials(db, connection_id, call.workspace_id)
        form = await signed_form(request, credentials)
        sid = form.get("CallSid")
        status = form.get("CallStatus")
        if call.provider_sid and call.provider_sid != sid:
            raise HTTPException(403, "Call mismatch")
        call.provider_sid = sid
        if call.status in TERMINAL and status != call.status:
            return {"ok": True}
        if call.ended_at and status not in TERMINAL:
            return {"ok": True}
        ranks = {
            "queued": 0,
            "initiated": 1,
            "ringing": 2,
            "in-progress": 3,
            "completed": 4,
            "busy": 4,
            "failed": 4,
            "no-answer": 4,
            "canceled": 4,
        }
        if status in ranks and ranks[status] >= ranks.get(call.status, -1):
            if call.status != status:
                event(db, call, "provider_status", {"status": status})
            call.status = status
            if status in TERMINAL:
                call.ended_at = call.ended_at or time.time()
                finish_recipient(db, call, status)
        db.commit()
        return {"ok": True}


async def update_twilio_call(call_id, twiml=None):
    with database().Session() as db:
        call = db.get(Call, call_id)
        credentials = twilio_credentials(db, call.connection_id, call.workspace_id)
        sid = call.provider_sid
    if not sid:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{credentials["account_sid"]}/Calls/{sid}.json',
            auth=twilio_auth(credentials),
            data={"Twiml": twiml} if twiml else {"Status": "completed"},
        )
        response.raise_for_status()


def wav_mulaw(encoded):
    with wave.open(io.BytesIO(base64.b64decode(encoded))) as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(
            np.float32
        )
        if wav.getnchannels() > 1:
            pcm = pcm.reshape(-1, wav.getnchannels()).mean(axis=1)
        rate = wav.getframerate()
    if not len(pcm):
        return b""
    samples = np.interp(
        np.arange(0, len(pcm), rate / 8000), np.arange(len(pcm)), pcm
    ).astype(np.int32)
    signs = np.where(samples < 0, 128, 0)
    samples = np.minimum(np.abs(samples), 32635) + 132
    exponent = np.floor(np.log2(samples)).astype(np.int32) - 7
    mantissa = (samples >> (exponent + 3)) & 15
    return ((~(signs | (exponent << 4) | mantissa)) & 255).astype(np.uint8).tobytes()


class PhoneTransport:
    def __init__(self, ws, stream_sid, call_id):
        self.ws = ws
        self.stream_sid = stream_sid
        self.call_id = call_id
        self.queue = asyncio.Queue(maxsize=2000)
        self.epoch = 0
        self.end_marks = {}
        self.session = None
        self.send_lock = asyncio.Lock()
        self.ended = False

    async def write(self, value):
        async with self.send_lock:
            await self.ws.send_json(value)

    async def send_text(self, value):
        data = json.loads(value)
        kind = data.get("type")
        if kind == "audio_clause":
            payload = await asyncio.to_thread(wav_mulaw, data["audio_b64"])
            epoch = self.epoch
            for start in range(0, len(payload), 160):
                await self.queue.put(
                    (epoch, "media", payload[start : start + 160].ljust(160, b"\xff"))
                )
        elif kind == "turn_complete":
            name = data.get("turn_id") or secrets.token_hex(8)
            if data.get("end_call"):
                self.end_marks[name] = True
            await self.queue.put((self.epoch, "mark", name))
        elif kind == "audio_unavailable":
            # Phone calls cannot use browser speech synthesis. End cleanly and
            # leave a staff task instead of silently continuing a text-only call.
            with database().Session() as db:
                call = db.get(Call, self.call_id)
                db.add(
                    StaffTask(
                        workspace_id=call.workspace_id,
                        call_id=call.id,
                        title="Voice provider unavailable",
                        details="The call could not play an assistant response.",
                    )
                )
                db.commit()
            await self.finish()

    async def clear(self):
        self.epoch += 1
        self.end_marks.clear()
        while not self.queue.empty():
            self.queue.get_nowait()
        await self.write({"event": "clear", "streamSid": self.stream_sid})

    async def play(self):
        deadline = time.monotonic()
        while True:
            epoch, kind, payload = await self.queue.get()
            if epoch != self.epoch:
                continue
            if kind == "media":
                await asyncio.sleep(max(0, deadline - time.monotonic()))
                if epoch != self.epoch:
                    continue
                await self.write(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": base64.b64encode(payload).decode()},
                    }
                )
                deadline = max(deadline, time.monotonic()) + 0.02
            else:
                await self.write(
                    {
                        "event": "mark",
                        "streamSid": self.stream_sid,
                        "mark": {"name": payload},
                    }
                )

    def normalize_input(self, message):
        return message

    async def finish(self, twiml=None):
        if twiml is None:
            await update_twilio_call(self.call_id)
        else:
            await update_twilio_call(self.call_id, twiml)

    async def mark(self, name):
        if name not in self.end_marks:
            return
        self.end_marks.pop(name, None)
        if self.session.transfer_requested:
            root = Element("Response")
            dial = SubElement(root, "Dial", timeout="20")
            SubElement(dial, "Number").text = self.session.config["transfer_number"]
            SubElement(root, "Say").text = (
                "The team is unavailable. Please contact the hospital directly."
            )
            SubElement(root, "Hangup")
            await self.finish(tostring(root, encoding="unicode"))
        else:
            await self.finish()


@router.websocket("/ws/telephony/{call_id}")
async def phone_socket(ws: WebSocket, call_id: str):
    with database().Session() as db:
        call = db.get(Call, call_id)
        if not call or call.ended_at or call.stream_claimed:
            await ws.close(code=4403)
            return
        try:
            credentials = twilio_credentials(db, call.connection_id, call.workspace_id)
            validator = RequestValidator(credentials["auth_token"])
            canonical = public_base() + ws.url.path
            candidates = {
                canonical,
                canonical + "/",
                canonical.replace("https://", "wss://", 1),
                canonical.replace("https://", "wss://", 1) + "/",
            }
            valid = any(
                validator.validate(url, {}, ws.headers.get("x-twilio-signature", ""))
                for url in candidates
            )
        except Exception:
            valid = False
        if not valid:
            await ws.close(code=4403)
            return
    await ws.accept()
    try:
        # Twilio sends connected and then start. Bind its SID and one-time token
        # to the persisted call before accepting any media.
        for _ in range(3):
            message = await asyncio.wait_for(ws.receive_json(), 10)
            if message.get("event") == "start":
                break
        start = message.get("start", {})
        with database().Session() as db:
            call = db.get(Call, call_id)
            if (
                start.get("callSid") != call.provider_sid
                or digest(start.get("customParameters", {}).get("token", ""))
                != call.stream_token_hash
            ):
                await ws.close(code=4403)
                return
            claimed = db.execute(
                update(Call)
                .where(Call.id == call.id, Call.stream_claimed == False)
                .values(stream_claimed=True)
            ).rowcount
            db.commit()
            if not claimed:
                await ws.close(code=4403)
                return
        await run_phone_session(ws, call_id, PhoneTransport(ws, start["streamSid"], call_id))
    except Exception:
        try:
            await ws.close(code=4403)
        except Exception:
            pass


async def run_phone_session(ws, call_id, transport):
    """Provider-independent audio/VAD/recognition and deterministic cleanup."""
    session = None
    player = None
    transport_failed = False
    try:
        from .runtime import session_class
        from app.web_server import cancel_turn, transcribe_turn
        from app.pipeline.call_audio import CallAudio

        session = session_class()(transport, call_id)
        transport.session = session
        await session.start_recognition()
        player = asyncio.create_task(transport.play())
        session.active_turn_task = asyncio.create_task(session.greet("greeting"))
        audio = CallAudio()
        speaking = False
        attack = 0
        silence = 0
        duration = 0
        noise = 0.002
        began = time.monotonic()
        recognition_turn = None
        pending_audio = bytearray()
        while True:
            if transport.ended:
                break
            if session.recognition_failed:
                await transport.finish()
                break
            if player.done():
                await transport.finish()
                break
            if (
                time.monotonic() - began > session.config["max_duration_seconds"]
                or time.monotonic() - session.last_activity
                > session.config["silence_timeout_seconds"]
            ):
                await transport.finish()
                break
            try:
                message = await asyncio.wait_for(ws.receive_json(), 1)
            except asyncio.TimeoutError:
                continue
            kind = message.get("event")
            if kind == "stop":
                break
            message = transport.normalize_input(message)
            kind = message.get("event")
            if kind == "mark":
                await transport.mark(message.get("mark", {}).get("name"))
                continue
            if kind != "media" or session.ending_call:
                continue
            frame = base64.b64decode(message["media"]["payload"], validate=True)
            if len(frame) > 8000:
                raise ValueError("Telephone audio frame exceeds one second")
            pending_audio.extend(frame)
            frames = len(pending_audio) // 160
            ready = bytes(pending_audio[:frames * 160])
            del pending_audio[:frames * 160]
            for offset in range(0, len(ready), 160):
                chunk = ready[offset : offset + 160]
                u = np.bitwise_not(np.frombuffer(chunk, dtype=np.uint8)).astype(
                    np.int32
                )
                magnitude = ((((u & 15) << 3) + 132) << ((u >> 4) & 7)) - 132
                rms = float(
                    np.sqrt(np.mean((magnitude.astype(np.float64) / 32768) ** 2))
                )
                threshold = max(0.009, noise * 2.8)
                if speaking and session.turn_completion and session.turn_completion.turn_id is None:
                    # The shared hard duration limit can commit during speech.
                    # Start a new bounded window for subsequent telephone audio.
                    speaking, attack, silence = False, 0, 0
                if not speaking:
                    if rms < threshold:
                        noise = noise * 0.98 + rms * 0.02
                    attack = attack + 1 if rms > threshold else max(0, attack - 2)
                    if attack >= 6:
                        speaking = True
                        silence = 0
                        duration = 6
                        await cancel_turn(session)
                        await transport.clear()
                        recognition_turn = secrets.token_hex(8)
                        if session.live_stt:
                            session.begin_recognition(recognition_turn)
                        else:
                            audio.start_speech()
                else:
                    duration += 1
                    silence = silence + 1 if rms < threshold * 0.65 else 0
                if session.live_stt:
                    await session.feed_recognition(chunk)
                else:
                    audio.feed(chunk)
                if speaking and (
                    silence * 20 >= (session.turn_completion.timing.complete_ms if session.turn_completion else session.config["end_pause_ms"]) or duration >= 1000
                ):
                    speaking = False
                    attack = 0
                    if session.live_stt:
                        await session.pause_recognition(recognition_turn, silence * 20, force=duration >= 1000)
                        continue
                    utterance = audio.end_speech()
                    if utterance:
                        session.active_turn_task = asyncio.create_task(
                            transcribe_turn(
                                session, utterance, "audio/wav", secrets.token_hex(8)
                            )
                        )
    except WebSocketDisconnect:
        pass
    except Exception:
        transport_failed = True
        # Avoid logging request bodies, patient speech, or decrypted credentials.
        if session:
            await session.persist(
                "error", {"message": "Telephone transport disconnected"}
            )
    finally:
        if session:
            session.is_active = False
            from app.web_server import cancel_turn

            await cancel_turn(session)
            await session.close_recognition()
            await session.close_record("failed" if session.recognition_failed or transport_failed else "completed")
        if player:
            player.cancel()
            try:
                await player
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:
            pass
