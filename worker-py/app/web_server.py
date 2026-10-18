"""
PulseMux - Real-Time Clinical Voice Studio Web Server
Combines:
  - Deepgram Nova-3 & Groq Whisper STT
  - Groq LPU (qwen/qwen3.8-27b) Clinical Triage
  - Local Kokoro-82M ONNX or Deepgram Aura-2 TTS
  - Real-time bi-directional browser WebSocket audio streaming
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
import threading
import uuid
import wave
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agent.tools import check_red_flag_symptoms, find_available_slots, book_appointment_slot
from app.pipeline.tts_stream import ClauseSplitter, KokoroEngine
from app.pipeline.call_audio import CallAudio
from app.pipeline.call_control import user_requested_hangup, assistant_said_farewell
from app.platform.api import router as platform_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("voice-studio")
TTS_LOCK = threading.Lock()
KOKORO_VOICES = {"af_bella", "af_sky", "am_adam", "am_michael", "bf_emma"}
DEEPGRAM_VOICES = {f"aura-2-{name}-en" for name in (
    "thalia", "andromeda", "helena", "apollo", "arcas", "aries", "pandora", "draco"
)}

app = FastAPI(title="PulseMux Clinical Voice Studio")
from app.platform.http_security import install_http_security
install_http_security(app)
from app.platform.observability import install_observability, router as diagnostics_router
install_observability(app)
app.include_router(diagnostics_router)

@app.on_event("startup")
async def warm_clinical_knowledge():
    from app.rag.integration import start
    await start()


@app.on_event("shutdown")
async def close_clinical_knowledge():
    from app.rag.integration import stop
    await stop()


app.include_router(platform_router)
from app.platform.resources import router as resource_router
app.include_router(resource_router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
INDEX_FILE = WEB_DIR / "index.html"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def platform_index():
    return RedirectResponse("/dashboard/")


@app.get("/simulator")
async def get_index():
    if INDEX_FILE.exists():
        return FileResponse(str(INDEX_FILE))
    return HTMLResponse("<h2>PulseMux Web UI not found</h2>", status_code=404)


@app.get('/readyz')
async def readyz():
    from app.platform.database import database
    from app.platform.security import cipher
    from sqlalchemy import text
    def check():
        with database().Session() as db: db.execute(text('SELECT 1'))
        cipher()
    await asyncio.to_thread(check)
    return {'status':'ready'}


@app.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "deepgram_configured": bool(os.getenv("DEEPGRAM_API_KEY")),
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "kokoro_ready": await asyncio.to_thread(KokoroEngine.get_instance) is not None,
    }


class VoiceSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.session_id = f"sess-{uuid.uuid4().hex[:8]}"
        self.messages: List[Dict[str, str]] = []
        self.is_active = True
        self.active_turn_task: Optional[asyncio.Task] = None
        self.stt_engine = "deepgram"  # "deepgram" or "groq"
        self.voice_id = "af_bella"
        self.tts_engine = "kokoro"
        self.tts_fallback_reason = None
        self.call_audio = CallAudio()
        self.ending_call = False
        self.keys_managed = False
        self.provider_keys = {}

    def provider_key(self, channel, env_name):
        return self.provider_keys.get(channel) if self.keys_managed else os.getenv(env_name)

    async def send_json(self, data: dict):
        if self.is_active:
            try:
                await self.ws.send_text(json.dumps(data))
            except Exception:
                self.is_active = False

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/webm") -> Optional[str]:
        """Transcribes incoming audio bytes using Deepgram Nova-3 or Groq Whisper."""
        t0 = time.time()
        deepgram_key = self.provider_key("stt", "DEEPGRAM_API_KEY") if self.stt_engine == "deepgram" else None
        groq_key = self.provider_key("stt", "GROQ_API_KEY") if self.stt_engine == "groq" else (None if self.keys_managed else os.getenv("GROQ_API_KEY"))

        # Prioritize Deepgram if selected and key available
        if self.stt_engine == "deepgram" and deepgram_key:
            try:
                headers = {
                    "Authorization": f"Token {deepgram_key}",
                    "Content-Type": mime_type if mime_type else "audio/webm",
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
                        headers=headers,
                        content=audio_bytes,
                    )
                    dt = (time.time() - t0) * 1000
                    if r.status_code == 200:
                        res = r.json()
                        transcript = res["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
                        await self.send_json({
                            "type": "telemetry_stt",
                            "engine": "Deepgram Nova-3",
                            "latency_ms": round(dt, 1),
                        })
                        return transcript
                    else:
                        logger.error("provider_failure provider=deepgram operation=stt status=%s", r.status_code)
            except Exception as e:
                logger.error("provider_failure provider=deepgram operation=stt")

        # Fallback / Direct Groq Whisper Turbo
        if groq_key:
            try:
                headers = {"Authorization": f"Bearer {groq_key}"}
                filename = "audio.webm" if "webm" in mime_type else "audio.wav"
                files = {"file": (filename, audio_bytes, mime_type)}
                data = {"model": "whisper-large-v3-turbo"}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers=headers,
                        files=files,
                        data=data,
                    )
                    dt = (time.time() - t0) * 1000
                    if r.status_code == 200:
                        transcript = r.json().get("text", "").strip()
                        await self.send_json({
                            "type": "telemetry_stt",
                            "engine": "Groq Whisper Turbo",
                            "latency_ms": round(dt, 1),
                        })
                        return transcript
                    else:
                        logger.error("provider_failure provider=groq operation=stt status=%s", r.status_code)
            except Exception as e:
                logger.error("provider_failure provider=groq operation=stt")

        return None

    async def synthesize_audio(self, clause: str, turn_id=None) -> Optional[str]:
        """Route every utterance (including greetings/farewells) to its TTS provider.

        The HTTP request stays on the event loop so interruption cancels it.
        Keys remain on the server; only encoded WAV audio reaches the browser.
        """
        if self.tts_engine == "deepgram":
            if not self.tts_fallback_reason:
                key = self.provider_key("tts", "DEEPGRAM_API_KEY")
                if not key:
                    self.tts_fallback_reason = "DEEPGRAM_API_KEY is not configured."
                else:
                    try:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            response = await client.post(
                                "https://api.deepgram.com/v1/speak",
                                params={"model": self.voice_id, "encoding": "linear16",
                                        "container": "wav", "sample_rate": 24000},
                                headers={"Authorization": f"Token {key}"},
                                json={"text": clause},
                            )
                            response.raise_for_status()
                            audio = response.content
                            if not (audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"):
                                raise ValueError("Invalid WAV response")
                            return base64.b64encode(audio).decode("ascii")
                    except httpx.HTTPStatusError as exc:
                        self.tts_fallback_reason = f"Deepgram returned HTTP {exc.response.status_code}."
                    except (httpx.RequestError, ValueError):
                        self.tts_fallback_reason = "Deepgram audio could not be generated."
                await self.send_json({"type": "tts_warning", "turn_id": turn_id,
                                      "message": self.tts_fallback_reason + " Using Kokoro or browser voice for this call."})
            # Keep fallback consistent for the rest of this call rather than
            # retrying a failed API on every clause. A new call resets this.
        return await asyncio.to_thread(self.synthesize_clause_wav, clause)

    def synthesize_clause_wav(self, clause: str) -> Optional[str]:
        # Cancelling an asyncio turn does not stop its synthesis thread. Serialize
        # access to the shared ONNX engine so the next turn cannot race that work.
        with TTS_LOCK:
            return self._synthesize_clause_wav(clause)

    def _synthesize_clause_wav(self, clause: str) -> Optional[str]:
        """Synthesizes text clause using Kokoro-82M ONNX and returns base64 WAV."""
        kokoro = KokoroEngine.get_instance()
        if not kokoro:
            return None

        try:
            samples, orig_rate = kokoro.create(clause, voice=self.voice_id if self.voice_id in KOKORO_VOICES else "af_bella", speed=1.0, lang="en-us")
            # Convert float32 [-1.0, 1.0] to int16 PCM
            pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(orig_rate)
                wf.writeframes(pcm16)
            return base64.b64encode(wav_buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.error("provider_failure provider=kokoro operation=tts")
            return None

    async def greet(self, turn_id):
        text = getattr(self, "greeting", "Hello, I am your PulseMux clinical assistant. How can I help you today?")
        self.messages.append({"role": "assistant", "content": text})
        await self.send_json({"type": "token", "delta": text, "turn_id": turn_id})
        audio = await self.synthesize_audio(text, turn_id)
        if audio:
            await self.send_json({"type": "audio_clause", "audio_b64": audio, "turn_id": turn_id})
        else:
            await self.send_json({"type": "audio_unavailable", "turn_id": turn_id})
        await self.send_json({"type": "turn_complete", "turn_id": turn_id, "total_turn_ms": 0})

    async def say_goodbye(self, turn_id):
        self.ending_call = True
        await self.send_json({"type": "call_ending", "turn_id": turn_id})
        text = "Thank you for calling. Goodbye."
        self.messages.append({"role": "assistant", "content": text})
        await self.send_json({"type": "token", "delta": text, "turn_id": turn_id})
        audio = await self.synthesize_audio(text, turn_id)
        if audio:
            await self.send_json({"type": "audio_clause", "audio_b64": audio, "turn_id": turn_id})
        else:
            await self.send_json({"type": "audio_unavailable", "turn_id": turn_id})
        await self.send_json({"type": "turn_complete", "turn_id": turn_id,
                              "total_turn_ms": 0, "end_call": True})

    async def handle_user_speech(self, user_text: str, turn_id: Optional[str] = None):
        """Processes user utterance, runs triage, streams tokens and Kokoro TTS."""
        turn_id = turn_id or f"turn-{uuid.uuid4().hex[:6]}"
        t_start = time.time()

        previous_reply = next((m["content"] for m in reversed(self.messages) if m["role"] == "assistant"), "")
        self.messages.append({"role": "user", "content": user_text})
        self.messages = self.messages[-40:]
        await self.send_json({
            "type": "transcript",
            "speaker": "PATIENT",
            "text": user_text,
            "turn_id": turn_id,
        })

        if user_requested_hangup(user_text, previous_reply):
            await self.say_goodbye(turn_id)
            return

        # Red flag evaluation
        red_flag_res = check_red_flag_symptoms(user_text)
        is_emergency = red_flag_res["is_emergency"]

        urgency_label = "EMERGENCY" if is_emergency else "ROUTINE"
        await self.send_json({
            "type": "triage_status",
            "is_emergency": is_emergency,
            "status": urgency_label,
            "matched_red_flags": red_flag_res.get("matched_red_flags", []),
            "turn_id": turn_id,
        })

        groq_key = self.provider_key("llm", "GROQ_API_KEY")
        if not groq_key:
            fallback_msg = (
                "Your symptoms indicate potential emergency distress. Please call 911 immediately."
                if is_emergency else
                "Thank you for sharing your symptoms. I can help book a consultation with our medical team."
            )
            await self.send_json({"type": "token", "delta": fallback_msg, "turn_id": turn_id})
            self.messages.append({"role": "assistant", "content": fallback_msg})
            b64_audio = await self.synthesize_audio(fallback_msg, turn_id)
            if b64_audio:
                await self.send_json({
                    "type": "audio_clause",
                    "text": fallback_msg,
                    "audio_b64": b64_audio,
                    "turn_id": turn_id,
                })
            else:
                await self.send_json({"type": "audio_unavailable", "turn_id": turn_id})
            await self.send_json({"type": "turn_complete", "turn_id": turn_id,
                                  "total_turn_ms": round((time.time() - t_start) * 1000, 1)})
            return

        system_prompt = (
            "You are PulseMux Clinical Emergency and Triage Voice AI. "
            "Your output is spoken aloud to the patient in real time over telephony or WebRTC. "
            "RULES: "
            "1. If patient shows RED FLAGS (chest pain, stroke symptoms, acute breathlessness, severe trauma): "
            "   Give calm, authoritative, immediate life-saving directives (call 911/112, sit upright, do not drive). "
            "2. If symptoms are non-emergency: "
            "   Acknowledge empathetically, offer concise clinical guidance, and offer to book an appointment with general medicine. "
            "3. Limit your spoken answer strictly to 1-2 clear, direct sentences. "
            "   Never output markdown asterisks, bullet points, or list numbers."
        )

        system_prompt = getattr(self, "system_prompt", system_prompt)
        messages = [{"role": "system", "content": system_prompt}]
        for m in self.messages[-5:]:
            messages.append({"role": m["role"], "content": m["content"]})

        clause_splitter = ClauseSplitter(min_word_count=5)
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": getattr(self, "llm_model", "qwen/qwen3.8-27b"),
            "messages": messages,
            "stream": True,
            "max_completion_tokens": 1024,
            "temperature": 0.2,
        }
        # Reasoning tokens share the completion budget with the spoken answer.
        # 120 tokens can exhaust GPT-OSS's budget before any content is emitted.
        if payload["model"] in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            payload["reasoning_effort"] = "low"

        first_token_time = None
        assistant_full_text = []
        audio_sent = False
        finish_reason = None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream(
                    "POST", getattr(self, "llm_endpoint", "https://api.groq.com/openai/v1/chat/completions"),
                    headers=headers, json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not self.is_active:
                            break
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            finish_reason = choices[0].get("finish_reason") or finish_reason
                            delta = choices[0].get("delta", {}).get("content") or ""
                            if delta:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                    ttft_ms = (first_token_time - t_start) * 1000
                                    await self.send_json({
                                        "type": "telemetry_ttft",
                                        "ttft_ms": round(ttft_ms, 1),
                                        "turn_id": turn_id,
                                    })

                                assistant_full_text.append(delta)
                                await self.send_json({
                                    "type": "token",
                                    "delta": delta,
                                    "turn_id": turn_id,
                                })

                                # Real-time clause extraction
                                new_clauses = clause_splitter.feed_token(delta)
                                for clause in new_clauses:
                                    t_tts = time.time()
                                    b64_audio = await self.synthesize_audio(clause, turn_id)
                                    tts_ms = (time.time() - t_tts) * 1000
                                    if b64_audio and self.is_active:
                                        audio_sent = True
                                        await self.send_json({
                                            "type": "audio_clause",
                                            "text": clause,
                                            "audio_b64": b64_audio,
                                            "turn_id": turn_id,
                                            "tts_ms": round(tts_ms, 1),
                                        })
                        except (json.JSONDecodeError, KeyError, TypeError):
                            continue

            if not "".join(assistant_full_text).strip():
                logger.warning("voice_empty_completion finish_reason=%s", finish_reason)
                await self.send_json({"type": "error", "turn_id": turn_id,
                                      "message": "The model returned no answer. Please try again or choose another model in the agent settings."})
                return

            # Flush remaining clause words
            trailing = clause_splitter.flush()
            if trailing and self.is_active:
                t_tts = time.time()
                b64_audio = await self.synthesize_audio(trailing, turn_id)
                tts_ms = (time.time() - t_tts) * 1000
                if b64_audio:
                    audio_sent = True
                    await self.send_json({
                        "type": "audio_clause",
                        "text": trailing,
                        "audio_b64": b64_audio,
                        "turn_id": turn_id,
                        "tts_ms": round(tts_ms, 1),
                    })

            if not audio_sent:
                await self.send_json({"type": "audio_unavailable", "turn_id": turn_id})
            complete_text = "".join(assistant_full_text).strip()
            if complete_text:
                self.messages.append({"role": "assistant", "content": complete_text})

            self.ending_call = assistant_said_farewell(complete_text)
            total_turn_ms = (time.time() - t_start) * 1000
            await self.send_json({
                "type": "turn_complete",
                "turn_id": turn_id,
                "total_turn_ms": round(total_turn_ms, 1),
                "end_call": self.ending_call,
            })

        except Exception as e:
            logger.error("voice_turn_failure")
            await self.send_json({"type": "error", "turn_id": turn_id,
                                  "message": "The assistant could not respond. Please try again."})


async def cancel_turn(session):
    task = session.active_turn_task
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    session.active_turn_task = None


async def transcribe_turn(session, audio, mime_type, turn_id):
    try:
        transcript = await session.transcribe_audio(audio, mime_type)
        if transcript:
            await session.handle_user_speech(transcript, turn_id)
        else:
            await session.send_json({"type": "stt_empty", "turn_id": turn_id,
                                     "message": "No speech recognized. Check your microphone or ASR configuration."})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("transcription_failure")
        await session.send_json({"type": "error", "turn_id": turn_id,
                                 "message": "Transcription failed. Please try again."})


@app.websocket("/ws/voice")
async def voice_websocket(ws: WebSocket):
    """Browser simulator: Twilio media envelopes plus local VAD control events.

    This is a local simulator endpoint, not a public Twilio webhook.
    """
    from app.platform.security import websocket_user
    try:
        user = websocket_user(ws)
        if user.role not in {"admin", "operator"}:
            await ws.close(code=4403)
            return
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    session = VoiceSession(ws)
    call_started = False
    await session.send_json({"type": "connected", "session_id": session.session_id})
    started_at = time.monotonic()
    checked_session_at = 0.0
    try:
        while True:
            if time.monotonic() - checked_session_at >= 1:
                try:
                    user = await asyncio.to_thread(websocket_user, ws)
                    if user.role not in {"admin", "operator"}:
                        await ws.close(code=4403)
                        break
                except HTTPException:
                    await ws.close(code=4401)
                    break
                checked_session_at = time.monotonic()
            if session.keys_managed and call_started:
                if time.monotonic()-started_at > session.config['max_duration_seconds'] or time.monotonic()-session.last_activity > session.config['silence_timeout_seconds']:
                    await cancel_turn(session)
                    await session.send_json({'type':'call_ended','message':'The call reached its duration or inactivity limit.'})
                    break
            try:
                data = await asyncio.wait_for(ws.receive(), 1.0)
            except asyncio.TimeoutError:
                continue
            if data["type"] == "websocket.disconnect":
                break
            if not data.get("text"):
                continue
            try:
                msg = json.loads(data["text"])
                kind = msg.get("type") or msg.get("event")
                if session.ending_call and kind not in {"stop", "start"}:
                    continue
                if kind == "config" and not session.keys_managed:
                    if msg.get("stt_engine") in {"deepgram", "groq"}:
                        session.stt_engine = msg["stt_engine"]
                    if not call_started and "voice_id" in msg:
                        voice = msg["voice_id"]
                        if voice in KOKORO_VOICES | DEEPGRAM_VOICES:
                            session.voice_id = voice
                            session.tts_engine = "deepgram" if voice in DEEPGRAM_VOICES else "kokoro"
                        else:
                            await session.send_json({"type": "error", "message": "Unsupported TTS voice."})
                elif kind == "start":
                    try:
                        user = await asyncio.to_thread(websocket_user, ws)
                        if user.role not in {"admin", "operator"}:
                            await ws.close(code=4403)
                            break
                    except HTTPException:
                        await ws.close(code=4401)
                        break
                    await cancel_turn(session)
                    if getattr(session, 'keys_managed', False):
                        await session.close_record()
                    from app.platform.database import database
                    from app.platform.service import runtime_bundle, event
                    from app.platform.models import Call
                    from app.platform.runtime import session_class
                    try:
                        with database().Session() as db:
                            agent, version, config, knowledge = runtime_bundle(db, user, msg.get('agent_id'), bool(msg.get('draft')))
                            if not version:
                                config['_draft_revision'] = agent.revision
                            call = Call(workspace_id=user.workspace_id,agent_id=agent.id,version_id=version.id if version else None,
                                        direction='simulation',config=config,knowledge=knowledge,variables={})
                            db.add(call);db.flush();event(db,call,'started',{'draft':version is None});db.commit()
                            call_id=call.id
                        session=session_class()(ws,call_id)
                    except Exception as exc:
                        await session.send_json({'type':'error','message':getattr(exc,'detail','Could not load this agent')})
                        continue
                    session.messages.clear()
                    session.ending_call = False
                    session.tts_fallback_reason = None
                    session.call_audio = CallAudio()
                    call_started = True
                    started_at = time.monotonic()
                    await session.send_json({"type": "call_started", "call_id":session.call_id, "settings":session.config, "agent_name":agent.name})
                    session.active_turn_task = asyncio.create_task(session.greet(msg.get("turn_id")))
                elif kind == "media" and call_started:
                    frame = base64.b64decode(msg["media"]["payload"], validate=True)
                    session.call_audio.feed(frame)
                elif kind in {"speech_start", "interrupt"} and call_started:
                    await cancel_turn(session)
                    if kind == "speech_start":
                        session.call_audio.start_speech()
                    await session.send_json({"type": "interrupted"})
                elif kind == "speech_end" and call_started:
                    audio = session.call_audio.end_speech()
                    if audio:
                        await cancel_turn(session)
                        session.active_turn_task = asyncio.create_task(
                            transcribe_turn(session, audio, "audio/wav", msg.get("turn_id")))
                elif kind == "user_text" and call_started:
                    text = str(msg.get("text", "")).strip()[:4000]
                    if text:
                        await cancel_turn(session)
                        session.active_turn_task = asyncio.create_task(
                            session.handle_user_speech(text, msg.get("turn_id")))
                elif kind == "stop":
                    call_started = False
                    await cancel_turn(session)
                    if session.keys_managed: await session.close_record()
                    session.call_audio = CallAudio()
                    await session.send_json({"type": "call_ended"})
            except (ValueError, KeyError, TypeError):
                await session.send_json({"type": "error", "message": "Invalid call audio message."})
    except WebSocketDisconnect:
        pass
    finally:
        session.is_active = False
        await cancel_turn(session)
        if session.keys_managed: await session.close_record()
        logger.info("Client disconnected: %s", session.session_id)


from app.platform.telephony import router as telephony_router
app.include_router(telephony_router)
DASHBOARD_DIR = WEB_DIR / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard/assets", StaticFiles(directory=str(DASHBOARD_DIR / "assets")), name="dashboard-assets")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_redirect():
        return RedirectResponse("/dashboard/")

    @app.get("/dashboard/{path:path}", include_in_schema=False)
    async def dashboard_application(path: str):
        return FileResponse(str(DASHBOARD_DIR / "index.html"))
else:
    @app.get("/dashboard/")
    async def dashboard_unbuilt():
        return HTMLResponse("<h1>Build the dashboard with: make dashboard-build</h1>", status_code=503)


def main():
    import uvicorn
    port = int(os.getenv("WEB_PORT", "8000"))
    logger.info(f"Starting PulseMux Clinical Voice Studio on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
