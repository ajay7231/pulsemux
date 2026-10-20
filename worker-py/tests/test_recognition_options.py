"""Preserve clinical entities across both providers' Deepgram transports."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.recognition_options import deepgram_options, validate_keyterms
from app.pipeline.live_stt import DeepgramCallStream
from app.platform.schemas import AgentConfig
from app.web_server import VoiceSession
from test_live_stt import Socket


class RecognitionPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_saved_vocabulary_is_bounded_deduplicated_and_backwards_compatible(self):
        self.assertEqual(AgentConfig().stt_keyterms, [])
        self.assertEqual(AgentConfig(stt_keyterms=[' Brilinta ', 'brilinta', 'Metoprolol  succinate']).stt_keyterms,
                         ['Brilinta', 'Metoprolol succinate'])
        for bad in [['term'] * 26, ['x' * 81], [''], ['Brilinta:10'], ['one two three four five six']]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_keyterms(bad)

    async def test_http_and_streaming_share_entity_preserving_policy_and_vocabulary(self):
        terms = ['Brilinta', 'metoprolol succinate']
        ws = Socket()
        connector = AsyncMock(return_value=ws)
        stream = DeepgramCallStream('key', AsyncMock(), AsyncMock(), connector=connector, keyterms=terms)
        await stream.start()
        await stream.close()
        url = connector.call_args.args[0]
        options = parse_qs(urlsplit(url).query)
        self.assertEqual(options['keyterm'], terms)
        self.assertEqual(options['smart_format'], ['false'])
        self.assertEqual(options['punctuate'], ['true'])
        self.assertEqual(options['language'], ['en'])
        trial = VoiceSession(AsyncMock())
        trial.keys_managed = True
        trial.provider_keys = {'stt': 'key'}
        trial.stt_keyterms = terms
        response = AsyncMock()
        response.status_code = 200
        response.json = lambda: {'results': {'channels': [{'alternatives': [{'transcript': 'Brilinta.'}]}]}}
        client = AsyncMock()
        client.post.return_value = response
        with patch('app.web_server.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            self.assertEqual(await trial.transcribe_audio(b'audio', 'audio/wav'), 'Brilinta.')
        self.assertEqual(client.post.call_args.kwargs['params'], deepgram_options(terms))
        for key, value in deepgram_options(terms).items():
            self.assertEqual(options[key], value if isinstance(value, list) else [value])

    async def test_low_confidence_turn_uses_own_audio_and_only_verified_text(self):
        import asyncio
        from test_live_stt import Socket, result
        socket = Socket()
        stream = DeepgramCallStream('key', AsyncMock(), AsyncMock(), connector=AsyncMock(return_value=socket))
        await stream.start()
        stream.begin_turn('one')
        for _ in range(65):
            stream.feed(b'\xff' * 160)
        await stream.queue.join()
        message = result(0, 1.3, [('cast', .1, .4)])
        message['channel']['alternatives'][0]['words'][0]['confidence'] = .7
        await socket.incoming.put(message)
        await asyncio.wait_for(stream.changed.wait(), .5)
        final = await stream.end_turn('one')
        self.assertEqual(final, 'cast')
        self.assertEqual(final.review_audio, b'\xff' * 160 * 65)
        trial = VoiceSession(AsyncMock())
        trial.transcribe_audio = AsyncMock(return_value='test')
        trial.handle_user_speech = AsyncMock()
        completed = asyncio.get_running_loop().create_future()
        completed.set_result(final)
        await trial.respond_to_recognition(completed, 'one')
        trial.handle_user_speech.assert_awaited_once_with('test', 'one')
        self.assertEqual(trial.transcribe_audio.await_count, 1)
        # A failed verification asks for repetition instead of forwarding uncertain words.
        trial.transcribe_audio.return_value = None
        trial.handle_user_speech.reset_mock()
        await trial.respond_to_recognition(completed, 'one')
        trial.handle_user_speech.assert_not_awaited()
        await stream.close()
        self.assertFalse(stream.audio_frames)
        self.assertFalse(stream.confidences)

    async def test_confident_turn_never_makes_second_recognition_request(self):
        import asyncio
        trial = VoiceSession(AsyncMock())
        trial.transcribe_audio = AsyncMock()
        trial.handle_user_speech = AsyncMock()
        done = asyncio.get_running_loop().create_future()
        done.set_result('Hello')
        await trial.respond_to_recognition(done, 'one')
        trial.transcribe_audio.assert_not_awaited()
        trial.handle_user_speech.assert_awaited_once_with('Hello', 'one')

    async def test_cancelled_verification_never_reaches_history_or_response(self):
        import asyncio
        from app.pipeline.live_stt import RecognitionTranscript
        trial = VoiceSession(AsyncMock())
        started = asyncio.Event()
        async def pending(*args):
            started.set()
            await asyncio.Future()
        trial.transcribe_audio = pending
        trial.handle_user_speech = AsyncMock()
        result = asyncio.get_running_loop().create_future()
        result.set_result(RecognitionTranscript('uncertain', b'\xff' * 160))
        task = asyncio.create_task(trial.respond_to_recognition(result, 'one'))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        trial.handle_user_speech.assert_not_awaited()
        self.assertEqual(trial.messages, [])

    async def test_failed_deepgram_never_switches_provider_even_with_groq_environment_key(self):
        trial = VoiceSession(AsyncMock())
        client = AsyncMock()
        client.post.side_effect = RuntimeError('simulated provider outage')
        with patch.dict('os.environ', {'DEEPGRAM_API_KEY': 'key', 'GROQ_API_KEY': 'another-key'}), patch('app.web_server.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            self.assertIsNone(await trial.transcribe_audio(b'audio', 'audio/wav'))
        self.assertEqual(client.post.await_count, 1)
        self.assertEqual(client.post.call_args.args[0], 'https://api.deepgram.com/v1/listen')
