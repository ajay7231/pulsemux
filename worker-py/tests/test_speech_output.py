"""Streaming playback boundaries, bounded flow and interruption without provider calls."""
import asyncio
import base64
import json
import unittest
from unittest.mock import patch

import httpx

from app.web_server import VoiceSession, cancel_turn
from app.pipeline.speech_output import DeepgramSpeechOutput, SpeechStreamError
from app.platform.telephony import PhoneTransport
from app.platform.plivo import PlivoTransport

RealClient = httpx.AsyncClient


class Socket:
    def __init__(self):
        self.messages = []
        self.audio = asyncio.Event()

    async def send_text(self, value):
        message = json.loads(value)
        self.messages.append(message)
        if message['type'] == 'audio_chunk':
            self.audio.set()


class GatedAudio(httpx.AsyncByteStream):
    def __init__(self, gate, *, fail=False):
        self.gate, self.fail, self.closed = gate, fail, False

    async def __aiter__(self):
        # Fragment across sample/frame boundaries to exercise byte reassembly.
        yield b'\x01'
        yield b'\x00' * 959
        await self.gate.wait()
        if self.fail:
            raise httpx.ReadError('synthetic failure')
        yield b'\x02\x00' * 480

    async def aclose(self):
        self.closed = True


class StreamingSpeechTests(unittest.IsolatedAsyncioTestCase):
    def session(self, **keys):
        session = VoiceSession(Socket())
        session.keys_managed = True
        session.provider_keys = {'tts': 'synthetic-key', **keys}
        session.tts_engine = 'deepgram'
        session.voice_id = 'aura-2-thalia-en'
        return session

    def clients(self, respond):
        return patch('app.web_server.httpx.AsyncClient', side_effect=lambda **kw:
                     RealClient(transport=httpx.MockTransport(respond), **kw))

    async def test_first_audio_arrives_before_provider_finishes_and_pool_is_reused(self):
        gate = asyncio.Event()
        stream = GatedAudio(gate)
        requests = []
        def respond(request):
            requests.append(request)
            self.assertEqual(request.url.params['container'], 'none')
            self.assertEqual(request.url.params['encoding'], 'linear16')
            return httpx.Response(200, stream=stream)
        session = self.session()
        with self.clients(respond) as clients:
            task = asyncio.create_task(session.speak('Synthetic greeting.', 't'))
            await asyncio.wait_for(session.ws.audio.wait(), 1)
            self.assertFalse(task.done())
            chunk = session.ws.messages[0]
            self.assertEqual(len(base64.b64decode(chunk['audio_b64'])), 960)
            self.assertEqual(chunk['sample_rate'], 24000)
            gate.set()
            self.assertTrue(await task)
            self.assertTrue(await session.speak('Second clause.', 't'))
            self.assertEqual(clients.call_count, 1)
            client = session.speech_output.client
            await session.close_recognition()
            self.assertTrue(client.is_closed)
        self.assertTrue(stream.closed)
        self.assertEqual(len(requests), 2)

    async def test_interrupt_closes_stream_and_no_audio_is_emitted_after_cancellation(self):
        stream = GatedAudio(asyncio.Event())
        session = self.session()
        with self.clients(lambda _: httpx.Response(200, stream=stream)), patch.object(session, 'synthesize_clause_wav') as fallback:
            session.active_turn_task = asyncio.create_task(session.greet('t'))
            await asyncio.wait_for(session.ws.audio.wait(), 1)
            await cancel_turn(session)
            count = len(session.ws.messages)
            await asyncio.sleep(0)
            self.assertEqual(count, len(session.ws.messages))
            fallback.assert_not_called()
            self.assertTrue(stream.closed)
            await session.close_recognition()
        self.assertFalse(any(m['type'] == 'turn_complete' for m in session.ws.messages))

    async def test_partial_audio_failure_never_replays_as_fallback(self):
        gate = asyncio.Event(); gate.set()
        stream = GatedAudio(gate, fail=True)
        session = self.session()
        with self.clients(lambda _: httpx.Response(200, stream=stream)), patch.object(session, 'synthesize_clause_wav') as fallback:
            with self.assertRaises(SpeechStreamError):
                await session.speak('Take only the prescribed dose.', 't')
            fallback.assert_not_called()
            await session.close_recognition()
        self.assertEqual([m['type'] for m in session.ws.messages], ['audio_chunk', 'audio_error'])
        self.assertNotIn('synthetic-key', json.dumps(session.ws.messages))

    async def test_failure_before_audio_uses_local_fallback_once(self):
        session = self.session()
        with self.clients(lambda _: httpx.Response(401)), patch.object(session, 'synthesize_clause_wav', return_value='local'):
            self.assertTrue(await session.speak('First.', 't'))
            self.assertTrue(await session.speak('Second.', 't'))
            await session.close_recognition()
        self.assertEqual([m['type'] for m in session.ws.messages], ['tts_warning', 'audio_clause', 'audio_clause'])

    async def test_llm_reading_continues_while_tts_is_waiting(self):
        gate = asyncio.Event()
        stream = GatedAudio(gate)
        async def respond(request):
            if request.url.path == '/v1/speak':
                return httpx.Response(200, stream=stream)
            chunks = [{'choices': [{'delta': {'content': text}}]} for text in
                      ['Please contact the hospital for assistance. ', 'The staff can help you.']]
            return httpx.Response(200, text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n')
        session = self.session(llm='synthetic-llm')
        with self.clients(respond):
            session.active_turn_task = asyncio.create_task(session.handle_user_speech('What are the visiting hours?', 't'))
            await asyncio.wait_for(session.ws.audio.wait(), 1)
            text = ''.join(m['delta'] for m in session.ws.messages if m['type'] == 'token')
            self.assertIn('The staff can help you.', text)
            self.assertTrue(any(m['type'] == 'text_complete' for m in session.ws.messages))
            self.assertFalse(session.active_turn_task.done())
            await cancel_turn(session)
            await session.close_recognition()
        self.assertTrue(stream.closed)
        self.assertFalse(any(m['type'] == 'turn_complete' for m in session.ws.messages))

    async def test_phone_frames_are_native_mulaw_for_both_adapters(self):
        seen = []
        def respond(request):
            self.assertEqual(request.url.params['encoding'], 'mulaw')
            self.assertEqual(request.url.params['sample_rate'], '8000')
            return httpx.Response(200, content=b'\xff' * 325)
        with self.clients(respond):
            output = DeepgramSpeechOutput()
            async for chunk, encoding, rate in output.chunks('Test', 'key', 'voice', phone=True):
                seen.append((chunk, encoding, rate))
            await output.close()
        for cls in (PhoneTransport, PlivoTransport):
            transport = cls(None, 'stream', 'call')
            for chunk, encoding, rate in seen:
                await transport.send_text(json.dumps({'type': 'audio_chunk', 'audio_b64':base64.b64encode(chunk).decode(),
                                                       'encoding':encoding,'sample_rate':rate}))
            self.assertEqual(transport.queue.qsize(), 3)
            frames = [transport.queue.get_nowait()[2] for _ in seen]
            self.assertTrue(all(len(frame) == 160 for frame in frames))
            self.assertEqual(b''.join(frames)[:325], b'\xff' * 325)
            with self.assertRaises(ValueError):
                await transport.send_text(json.dumps({'type':'audio_chunk','encoding':'linear16','sample_rate':24000}))

    async def test_clauses_are_bounded_when_synthesis_is_blocked(self):
        session = self.session(llm='synthetic-llm')
        entered = asyncio.Event()
        async def blocked(text, turn):
            entered.set()
            await asyncio.Event().wait()
        chunks = [{'choices':[{'delta':{'content':f'Please contact hospital staff for question {i}. '}}]} for i in range(100)]
        body = ''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        with self.clients(lambda _: httpx.Response(200, text=body)), patch.object(session, 'speak', blocked):
            session.active_turn_task = asyncio.create_task(session.handle_user_speech('What are the visiting hours?', 't'))
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            tokens = [m for m in session.ws.messages if m['type'] == 'token']
            self.assertLessEqual(len(tokens), 6)
            await cancel_turn(session)
            await session.close_recognition()

    def test_splitter_emits_short_sentences_and_preserves_decimal_doses(self):
        from app.pipeline.tts_stream import ClauseSplitter
        splitter = ClauseSplitter(min_word_count=5)
        self.assertEqual(splitter.feed_token('Hello there. How can I help? '), ['Hello there.', 'How can I help?'])
        self.assertEqual(splitter.feed_token('The prescribed dose is 90.'), [])
        self.assertEqual(splitter.feed_token('5 mg. Please verify it. '), ['The prescribed dose is 90.5 mg.', 'Please verify it.'])
        self.assertIsNone(splitter.flush())
