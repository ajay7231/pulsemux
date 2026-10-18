import asyncio
import base64
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web_server import VoiceSession, DEEPGRAM_VOICES, KOKORO_VOICES, INDEX_FILE, app
from app.pipeline.call_audio import mulaw_wav
from fastapi.testclient import TestClient
from platform_support import platform_client, create_agent

RealAsyncClient = httpx.AsyncClient


class Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, value):
        self.messages.append(json.loads(value))


class DeepgramTTSTests(unittest.IsolatedAsyncioTestCase):
    def session(self):
        session = VoiceSession(Socket())
        session.tts_engine = 'deepgram'
        session.voice_id = 'aura-2-thalia-en'
        return session

    async def test_selected_voice_used_for_greeting_reply_and_goodbye(self):
        session = self.session()
        audio = mulaw_wav(b'\xff' * 160)
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(request.url.path, '/v1/speak')
            self.assertEqual(request.url.params['model'], session.voice_id)
            self.assertEqual(request.url.params['encoding'], 'linear16')
            self.assertEqual(request.url.params['container'], 'wav')
            self.assertEqual(request.url.params['sample_rate'], '24000')
            self.assertEqual(request.headers['authorization'], 'Token test-only-key')
            return httpx.Response(200, content=audio)

        with patch.dict('os.environ', {'DEEPGRAM_API_KEY': 'test-only-key', 'GROQ_API_KEY': ''}), patch(
            'app.web_server.httpx.AsyncClient', side_effect=lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        ), patch.object(session, 'synthesize_clause_wav') as kokoro:
            await session.greet('greeting')
            await session.handle_user_speech('Hello', 'reply')
            await session.handle_user_speech('End the call please', 'goodbye')
            kokoro.assert_not_called()
        self.assertEqual(len(requests), 3)
        clauses = [m for m in session.ws.messages if m['type'] == 'audio_clause']
        self.assertEqual([m['turn_id'] for m in clauses], ['greeting', 'reply', 'goodbye'])
        self.assertTrue(all(base64.b64decode(m['audio_b64']) == audio for m in clauses))
        self.assertTrue(session.ws.messages[-1]['end_call'])

    async def test_failure_reports_once_and_uses_consistent_local_fallback(self):
        session = self.session()
        requests = []
        def fail(request):
            requests.append(request)
            return httpx.Response(401, json={'error': 'unauthorized'})
        with patch.dict('os.environ', {'DEEPGRAM_API_KEY': 'test-only-key'}), patch(
            'app.web_server.httpx.AsyncClient', side_effect=lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(fail), **kwargs)
        ), patch.object(session, 'synthesize_clause_wav', return_value='local-audio'):
            self.assertEqual(await session.synthesize_audio('First', 't'), 'local-audio')
            self.assertEqual(await session.synthesize_audio('Second', 't'), 'local-audio')
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(session.ws.messages), 1)
        self.assertIn('HTTP 401', session.ws.messages[0]['message'])
        self.assertNotIn('test-only-key', json.dumps(session.ws.messages))

    async def test_missing_key_falls_back_without_http_request(self):
        session = self.session()
        with patch.dict('os.environ', {'DEEPGRAM_API_KEY': ''}), patch('app.web_server.httpx.AsyncClient') as client, patch.object(
            session, 'synthesize_clause_wav', return_value=None
        ):
            self.assertIsNone(await session.synthesize_audio('Hello', 't'))
            client.assert_not_called()
        self.assertIn('DEEPGRAM_API_KEY', session.ws.messages[0]['message'])

    async def test_interrupt_cancels_deepgram_request_without_starting_fallback(self):
        session = self.session()
        entered = asyncio.Event()
        async def pending(request):
            entered.set()
            await asyncio.Event().wait()
        with patch.dict('os.environ', {'DEEPGRAM_API_KEY': 'test-only-key'}), patch(
            'app.web_server.httpx.AsyncClient', side_effect=lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(pending), **kwargs)
        ), patch.object(session, 'synthesize_clause_wav') as fallback:
            task = asyncio.create_task(session.synthesize_audio('Hello', 't'))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            fallback.assert_not_called()
        self.assertEqual(session.ws.messages, [])

    def test_ui_voice_options_match_server_allowlist(self):
        options = set(re.findall(r'<option value="([^"]+)"', INDEX_FILE.read_text())) - {'deepgram', 'groq'}
        self.assertEqual(options, KOKORO_VOICES | DEEPGRAM_VOICES)

    def test_websocket_configuration_selects_deepgram_provider(self):
        async def greet(session, turn_id):
            await session.send_json({'type': 'test_config', 'provider': session.tts_engine, 'voice': session.voice_id})
        with patch.object(VoiceSession, 'greet', greet), platform_client() as client:
            agent=create_agent(client,tts_engine='deepgram',voice_id='aura-2-helena-en',stt_engine='groq')
            with client.websocket_connect('/ws/voice') as ws:
                ws.receive_json()
                ws.send_json({'event': 'start', 'turn_id': 'greeting', 'agent_id':agent['id'], 'draft':True})
                self.assertEqual(ws.receive_json()['type'], 'call_started')
                self.assertEqual(ws.receive_json(), {'type': 'test_config', 'provider': 'deepgram', 'voice': 'aura-2-helena-en'})
