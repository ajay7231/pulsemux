import asyncio
import base64
import io
import json
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.call_audio import CallAudio, mulaw_wav
from app.pipeline.call_control import user_requested_hangup, assistant_said_farewell
from app.web_server import app, VoiceSession
from fastapi.testclient import TestClient
from platform_support import platform_client, create_agent


class AudioTests(unittest.TestCase):
    def test_simulator_page_and_audio_assets_are_served(self):
        with TestClient(app) as client:
            page = client.get('/simulator')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Start call', page.text)
            self.assertNotIn('Tap to Speak', page.text)
            self.assertEqual(client.get('/static/call.js').status_code, 200)
            self.assertEqual(client.get('/static/mic-worklet.js').status_code, 200)

    def test_hangup_intent_is_conservative(self):
        for text in ('End the call, please.', 'Can you hang up please?', 'Goodbye!', 'Please end this call now.'):
            with self.subTest(text=text):
                self.assertTrue(user_requested_hangup(text))
        for text in ("Don't end the call", 'How do I end the call?', 'The last call ended', 'No, thank you, but my head hurts', 'Thank you', 'No'):
            with self.subTest(text=text):
                self.assertFalse(user_requested_hangup(text))
        self.assertFalse(user_requested_hangup('No. Thank you.', 'Do you have a fever?'))
        self.assertTrue(user_requested_hangup('No. Thank you.', 'Do you have any other symptoms, or would you like to book an appointment?'))
        self.assertTrue(assistant_said_farewell('You are welcome. Have a good day.'))
        self.assertFalse(assistant_said_farewell('Would you like to book an appointment?'))

    def test_explicit_hangup_produces_action_without_llm(self):
        class Socket:
            def __init__(self): self.messages = []
            async def send_text(self, text): self.messages.append(json.loads(text))
        for text, previous in [('End the call, please.', ''), ('No. Thank you.', 'Do you have any other symptoms?')]:
            socket = Socket()
            session = VoiceSession(socket)
            session.messages = [{"role": "assistant", "content": previous}]
            with patch.object(VoiceSession, 'synthesize_clause_wav', return_value=None):
                asyncio.run(session.handle_user_speech(text, 'closing'))
            self.assertTrue(session.ending_call)
            self.assertTrue(socket.messages[-1]['end_call'])
            self.assertEqual(socket.messages[-1]['turn_id'], 'closing')
            self.assertTrue(any(m['type'] == 'call_ending' for m in socket.messages))
            self.assertTrue(any(m['type'] == 'audio_unavailable' for m in socket.messages))

    def test_standard_mulaw_vectors(self):
        with wave.open(io.BytesIO(mulaw_wav(bytes([255, 127, 128, 0])))) as wav:
            self.assertEqual(wav.getframerate(), 8000)
            self.assertEqual(wav.getnchannels(), 1)
            import struct
            self.assertEqual(struct.unpack('<4h', wav.readframes(4)), (0, 0, 32124, -32124))

    def test_preroll_and_bounded_capture(self):
        audio = CallAudio()
        for _ in range(100):
            audio.feed(b'\xff' * 160)
        self.assertEqual(len(audio.preroll), 15)
        audio.start_speech()
        for _ in range(2000):
            audio.feed(b'\xff' * 160)
        self.assertEqual(len(audio.frames), 1050)
        self.assertIsNotNone(audio.end_speech())
        self.assertIsNone(audio.end_speech())
        with self.assertRaises(ValueError):
            audio.feed(b'invalid')

    def test_call_transcription_and_interrupt_are_nonblocking(self):
        cancelled = []
        async def greet(session, turn_id):
            await session.send_json({'type': 'turn_complete', 'turn_id': turn_id})
        async def transcribe(session, audio, mime):
            self.assertTrue(audio.startswith(b'RIFF'))
            self.assertEqual(mime, 'audio/wav')
            await session.send_json({'type': 'test_transcribing'})
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        with patch.object(VoiceSession, 'greet', greet), patch.object(VoiceSession, 'transcribe_audio', transcribe):
            with platform_client() as client:
                agent=create_agent(client)
                with client.websocket_connect('/ws/voice') as ws:
                    self.assertEqual(ws.receive_json()['type'], 'connected')
                    ws.send_json({'event': 'start', 'turn_id': 'greeting', 'agent_id':agent['id'], 'draft':True})
                    self.assertEqual(ws.receive_json()['type'], 'call_started')
                    self.assertEqual(ws.receive_json()['turn_id'], 'greeting')
                    ws.send_json({'type': 'speech_start'})
                    self.assertEqual(ws.receive_json()['type'], 'interrupted')
                    ws.send_json({'event': 'media', 'media': {'payload': base64.b64encode(b'\xff' * 160).decode()}})
                    ws.send_json({'type': 'speech_end', 'turn_id': 't1'})
                    self.assertEqual(ws.receive_json()['type'], 'test_transcribing')
                    ws.send_json({'type': 'interrupt'})
                    self.assertEqual(ws.receive_json()['type'], 'interrupted')
                    ws.send_json({'event': 'stop'})
                    self.assertEqual(ws.receive_json()['type'], 'call_ended')
        self.assertEqual(cancelled, [True])

    def test_fallback_response_completes(self):
        class Socket:
            def __init__(self): self.messages = []
            async def send_text(self, text): self.messages.append(json.loads(text))
        socket = Socket()
        with patch.dict('os.environ', {'GROQ_API_KEY': ''}), patch.object(VoiceSession, 'synthesize_clause_wav', return_value=None):
            asyncio.run(VoiceSession(socket).handle_user_speech('Hello', 'test'))
        self.assertEqual(socket.messages[-1]['type'], 'turn_complete')
        self.assertEqual(socket.messages[-1]['turn_id'], 'test')
        self.assertTrue(any(m['type'] == 'audio_unavailable' for m in socket.messages))


if __name__ == '__main__':
    unittest.main()
