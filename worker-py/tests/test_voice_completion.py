"""A provider stream must produce an answer or a visible terminal error."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web_server import VoiceSession


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self, chunks, tts_error=False):
        events, requests = [], []

        class Socket:
            async def send_text(self, value):
                events.append(json.loads(value))

        def respond(request):
            requests.append(json.loads(request.content))
            body = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks)
            return httpx.Response(200, text=body + 'data: [DONE]\n\n')

        real_client = httpx.AsyncClient
        session = VoiceSession(Socket())
        session.keys_managed = True
        session.provider_keys = {'llm': 'test-key'}
        session.llm_model = 'openai/gpt-oss-120b'
        synth = AsyncMock(return_value=None, side_effect=RuntimeError('tts failed') if tts_error else None)
        with patch('app.web_server.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)), patch.object(session, 'synthesize_audio', synth):
            await session.handle_user_speech('What are the visiting hours?', 'test-turn')
        return events, requests, session

    async def test_reasoning_only_completion_is_visible_error(self):
        events, requests, session = await self.run_stream([
            {'choices': [{'delta': {'reasoning': 'internal'}, 'finish_reason': None}]},
            {'choices': [{'delta': {}, 'finish_reason': 'length'}]},
        ])
        self.assertEqual(requests[0]['max_completion_tokens'], 1024)
        self.assertEqual(requests[0]['reasoning_effort'], 'low')
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(events[-1]['turn_id'], 'test-turn')
        self.assertFalse(any(e['type'] == 'turn_complete' for e in events))
        self.assertFalse(any(m['role'] == 'assistant' for m in session.messages))

    async def test_content_and_usage_frames_complete_normally(self):
        events, _, session = await self.run_stream([
            {'choices': [{'delta': {'content': 'Please contact reception for visiting hours.'}}]},
            {'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': {'completion_tokens': 12}},
        ])
        self.assertEqual(events[-1]['type'], 'turn_complete')
        self.assertTrue(any(e['type'] == 'audio_unavailable' for e in events))
        self.assertEqual(session.messages[-1]['content'], 'Please contact reception for visiting hours.')

    async def test_tts_exception_is_not_swallowed(self):
        events, _, _ = await self.run_stream([
            {'choices': [{'delta': {'content': 'Please contact reception for visiting hours.'}}]},
        ], tts_error=True)
        self.assertEqual(events[-1]['type'], 'error')
