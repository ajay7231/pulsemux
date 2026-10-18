"""Streaming boundaries, late provider results, and call-owned resource cleanup."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.live_stt import DeepgramCallStream, RecognitionUnavailable
from app.web_server import VoiceSession


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.incoming.get()
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)

    async def send(self, payload):
        await self.sent.put(payload)

    async def close(self):
        self.closed = True
        await self.incoming.put(None)


def result(start, end, words=(), final=True, **extra):
    return {"type": "Results", "start": start, "duration": end - start,
            "is_final": final, "channel": {"alternatives": [{
                "transcript": " ".join(w[0] for w in words),
                "words": [{"word": text, "start": a, "end": b} for text, a, b in words]}]}, **extra}


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = Socket()
        self.failure, self.interim = AsyncMock(), AsyncMock()
        self.connector = AsyncMock(return_value=self.socket)
        self.stream = DeepgramCallStream('workspace-key', self.interim, self.failure,
                                         connector=self.connector, finalize_timeout=.1,
                                         keepalive_seconds=.02)
        await self.stream.start()

    async def asyncTearDown(self):
        await self.stream.close()

    async def feed(self, count):
        for _ in range(count):
            self.stream.feed(b'\xff' * 160)
        await self.stream.queue.join()

    async def deliver(self, value):
        self.stream.changed.clear()
        await self.socket.incoming.put(value)
        await asyncio.wait_for(self.stream.changed.wait(), .5)

    async def test_segments_and_duplicate_final_do_not_duplicate_words(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        await self.deliver(result(0, .3, [('Hello', .1, .25)], final=False, speech_final=True))
        self.interim.assert_awaited_once_with('one', 'Hello')
        self.assertEqual(self.stream.words, {})
        first = result(0, .3, [('Hello', .1, .25)])
        await self.deliver(first)
        await self.deliver(first)
        await self.deliver(result(.3, .5, [('there.', .32, .49)]))
        self.assertEqual(await self.stream.end_turn('one'), 'Hello there.')
        self.assertEqual(self.connector.await_count, 1)

    async def test_late_old_results_do_not_finish_or_contaminate_new_turn(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        old = result(0, 1.3, [('Hello', .1, .4)], from_finalize=True)
        await self.deliver(old)
        self.assertEqual(await self.stream.end_turn('one'), 'Hello')
        self.stream.begin_turn('two')
        await self.feed(65)
        pending = self.stream.end_turn('two')
        await self.deliver(old)
        self.assertFalse(pending.done())
        await self.deliver(result(1.3, 2.6, [('Hello', 1.4, 1.7)], from_finalize=True))
        self.assertEqual(await pending, 'Hello')
        self.assertEqual(self.connector.await_count, 1)

    async def test_interruption_does_not_cancel_provider_flush(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        pending = self.stream.end_turn('one')
        async def response():
            return await asyncio.shield(pending)
        waiter = asyncio.create_task(response())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.stream.begin_turn('two')
        await self.feed(65)
        second = self.stream.end_turn('two')
        await self.deliver(result(0, 1.3, [('Old', .1, .4)], from_finalize=True))
        self.assertEqual(await pending, 'Old')
        await self.deliver(result(1.3, 2.6, [('New', 1.4, 1.7)], from_finalize=True))
        self.assertEqual(await second, 'New')

    async def test_missing_ack_uses_final_coverage_not_interim_text(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        await self.deliver(result(0, .5, [('Ready.', .1, .49)]))
        self.assertEqual(await self.stream.end_turn('one'), 'Ready.')

    async def test_finalization_timeout_fails_visibly(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        await self.deliver(result(0, .5, [('Unconfirmed', .1, .49)], final=False))
        with self.assertRaises(RecognitionUnavailable):
            await self.stream.end_turn('one')
        self.failure.assert_awaited_once()
        self.assertTrue(self.stream.failed)

    async def test_old_final_preserves_newer_incomplete_interim_suffix(self):
        observations = []
        self.stream.on_result = lambda turn, text, **flags: observations.append((text, flags))
        self.stream.begin_turn('one')
        await self.feed(100)
        await self.deliver(result(.6, 1.2, [('and', .7, 1.1)], final=False))
        await self.deliver(result(0, .6, [('Yesterday.', .1, .5)], speech_final=True))
        self.assertEqual(observations[-1][0], 'Yesterday. and')
        self.interim.assert_awaited_with('one', 'Yesterday. and')
        self.assertFalse(observations[-1][1]['is_final'])
        self.assertFalse(observations[-1][1]['speech_final'])

    async def test_continuation_preserves_finalized_prefix_in_one_turn(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        await self.deliver(result(0, 1.3, [('I feel', .1, .4)]))
        self.stream.begin_turn('continued', continue_turn=True)
        await self.feed(65)
        await self.deliver(result(1.3, 2.6, [('dizzy.', 1.4, 1.7)]))
        self.assertEqual(await self.stream.end_turn('continued'), 'I feel dizzy.')

    async def test_session_continuation_commits_combined_text_once(self):
        from app.pipeline.turn_completion import SemanticTurnCompletion
        from test_turn_completion import VirtualClock
        clock, socket = VirtualClock(), AsyncMock()
        session = VoiceSession(socket)
        session.live_stt = self.stream
        session.handle_user_speech = AsyncMock()
        policy = SemanticTurnCompletion(session.commit_semantic_turn, self.failure,
                                        clock=clock, sleep=clock.sleep)
        session.turn_completion = policy
        self.stream.on_result = policy.observe
        try:
            session.begin_recognition('one')
            await self.feed(65)
            await self.deliver(result(0, 1.3, [('I have been feeling', .1, .4)]))
            await session.pause_recognition('one', 360)
            await clock.advance(640)
            session.handle_user_speech.assert_not_awaited()
            session.begin_recognition('continued')
            await self.feed(65)
            await self.deliver(result(1.3, 2.6, [('dizzy since yesterday.', 1.4, 1.8)]))
            await session.pause_recognition('continued', 360)
            await clock.advance(10)
            await asyncio.wait_for(session.active_turn_task, .5)
            session.handle_user_speech.assert_awaited_once_with(
                'I have been feeling dizzy since yesterday.', 'continued')
            commits = [json.loads(call.args[0]) for call in socket.send_text.call_args_list
                       if json.loads(call.args[0])['type'] == 'turn_committed']
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0]['turn_id'], 'continued')
        finally:
            await policy.close()
        self.assertEqual(policy.tasks, set())

    async def test_empty_finalized_turn_does_not_generate_or_disconnect(self):
        from app.pipeline.turn_completion import SemanticTurnCompletion
        from test_turn_completion import VirtualClock
        clock, socket = VirtualClock(), AsyncMock()
        session = VoiceSession(socket)
        session.live_stt = self.stream
        session.handle_user_speech = AsyncMock()
        policy = SemanticTurnCompletion(session.commit_semantic_turn, self.failure,
                                        clock=clock, sleep=clock.sleep)
        session.turn_completion = policy
        self.stream.on_result = policy.observe
        try:
            session.begin_recognition('empty')
            await self.feed(65)
            await self.deliver(result(0, 1.3))
            await session.pause_recognition('empty', 360)
            await clock.advance(850)
            await asyncio.wait_for(session.active_turn_task, .5)
            session.handle_user_speech.assert_not_awaited()
            events = [json.loads(call.args[0])['type'] for call in socket.send_text.call_args_list]
            self.assertIn('stt_empty', events)
            self.assertNotIn('call_ended', events)
            self.failure.assert_not_awaited()
        finally:
            await policy.close()

    async def test_keepalive_and_disconnect_and_cleanup(self):
        message = await asyncio.wait_for(self.socket.sent.get(), .5)
        self.assertEqual(json.loads(message)['type'], 'KeepAlive')
        await self.socket.incoming.put(None)
        for _ in range(10):
            await asyncio.sleep(0)
            if self.stream.failed:
                break
        self.failure.assert_awaited_once()
        tasks = list(self.stream.tasks)
        await self.stream.close()
        self.assertTrue(self.socket.closed)
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.stream.words, {})

    async def test_failure_log_excludes_provider_message_and_transcripts(self):
        with self.assertLogs('app.pipeline.live_stt', level='WARNING') as logs:
            await self.stream._fail('socket_read_or_result_validation',
                                    RuntimeError('private-key patient transcript'))
        entry = ' '.join(logs.output)
        self.assertIn('reason=socket_read_or_result_validation', entry)
        self.assertIn('exception_type=RuntimeError', entry)
        self.assertNotIn('private-key', entry)
        self.assertNotIn('patient transcript', entry)

    async def test_backlog_is_bounded_and_calls_are_isolated(self):
        other = DeepgramCallStream('other-key', AsyncMock(), AsyncMock(), connector=AsyncMock(return_value=Socket()))
        await other.start()
        try:
            for _ in range(250):
                self.stream.feed(b'\xff' * 160)
            with self.assertRaises(RecognitionUnavailable):
                self.stream.feed(b'\xff' * 160)
            self.assertEqual(other.samples, 0)
            self.assertEqual(other.words, {})
        finally:
            await other.close()

    async def test_close_interrupts_waiting_finalization(self):
        self.stream.begin_turn('one')
        await self.feed(65)
        pending = self.stream.end_turn('one')
        await asyncio.sleep(0)
        await self.stream.close()
        self.assertTrue(pending.done())
        self.assertEqual(self.stream.collectors, set())


class SessionRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_groq_does_not_open_deepgram_and_rollback_is_explicit(self):
        session = VoiceSession(AsyncMock())
        session.keys_managed = True
        session.provider_keys = {'stt': 'saved-key'}
        with patch('app.pipeline.live_stt.connect_deepgram', new_callable=AsyncMock) as connector:
            session.stt_engine = 'groq'
            await session.start_recognition()
            self.assertIsNone(session.live_stt)
            session.stt_engine = 'deepgram'
            with patch.dict('os.environ', {'DEEPGRAM_STREAMING_ENABLED': '0'}):
                await session.start_recognition()
            self.assertIsNone(session.live_stt)
            connector.assert_not_awaited()

    async def test_startup_failure_uses_saved_key_and_does_not_expose_provider_error(self):
        session = VoiceSession(AsyncMock())
        session.keys_managed = True
        session.provider_keys = {'stt': 'saved-private-key'}
        failure = AsyncMock(side_effect=RuntimeError('provider echoed saved-private-key'))
        with patch.dict('os.environ', {'DEEPGRAM_STREAMING_ENABLED': '1', 'DEEPGRAM_API_KEY': 'wrong-global-key'}), patch(
            'app.pipeline.live_stt.connect_deepgram', failure
        ):
            with self.assertRaises(RecognitionUnavailable) as error:
                await session.start_recognition()
        self.assertNotIn('saved-private-key', str(error.exception))
        self.assertEqual(failure.call_args.args[1], 'saved-private-key')
        self.assertTrue(session.recognition_failed)
        self.assertIsNone(session.live_stt.key)
        await session.close_recognition()

    async def test_streaming_failure_is_terminal_and_sanitized(self):
        socket = AsyncMock()
        session = VoiceSession(socket)
        await session.recognition_failure()
        await session.recognition_failure()
        self.assertEqual(socket.send_text.await_count, 2)
        self.assertEqual(json.loads(socket.send_text.call_args.args[0])['type'], 'call_ended')


class AutoSocket(Socket):
    """Provider emulator that only finalizes when the transport commits a turn."""
    def __init__(self):
        super().__init__()
        self.audio_bytes = 0

    async def send(self, payload):
        await super().send(payload)
        if isinstance(payload, bytes):
            self.audio_bytes += len(payload)
        elif json.loads(payload)['type'] == 'Finalize':
            end = self.audio_bytes / 8000
            await self.incoming.put(result(0, end, [('Hello.', .1, min(.3, end))], from_finalize=True))


class BrowserStreamingIntegrationTests(unittest.TestCase):
    def test_saved_connection_one_response_and_socket_cleanup(self):
        from platform_support import platform_client, create_agent
        sockets, keys, handled = [], [], []

        async def connect(url, key):
            self.assertIn('encoding=mulaw', url)
            self.assertIn('sample_rate=8000', url)
            self.assertIn('endpointing=350', url)
            keys.append(key)
            socket = AutoSocket()
            sockets.append(socket)
            return socket

        async def greet(session, turn_id):
            await session.send_json({'type': 'turn_complete', 'turn_id': turn_id})

        async def handle(session, text, turn_id=None):
            handled.append((text, turn_id))
            await session.send_json({'type': 'transcript', 'text': text, 'turn_id': turn_id})
            await session.send_json({'type': 'turn_complete', 'turn_id': turn_id})

        import base64
        with platform_client() as client:
            agent = create_agent(client)
            with patch.dict('os.environ', {'DEEPGRAM_STREAMING_ENABLED': '1', 'SEMANTIC_TURN_ENABLED': '1'}), patch(
                'app.pipeline.live_stt.connect_deepgram', connect
            ), patch.object(VoiceSession, 'greet', greet), patch.object(VoiceSession, 'handle_user_speech', handle):
                with client.websocket_connect('/ws/voice') as ws:
                    self.assertEqual(ws.receive_json()['type'], 'connected')
                    ws.send_json({'event': 'start', 'turn_id': 'greeting', 'agent_id': agent['id'], 'draft': True})
                    started = ws.receive_json()
                    self.assertEqual(started['type'], 'call_started')
                    self.assertTrue(started['turn_detection']['semantic'])
                    self.assertEqual(ws.receive_json()['type'], 'turn_complete')
                    ws.send_json({'type': 'speech_start', 'turn_id': 'one'})
                    self.assertEqual(ws.receive_json()['type'], 'interrupted')
                    for _ in range(65):
                        ws.send_json({'event': 'media', 'media': {'payload': base64.b64encode(b'\xff' * 160).decode()}})
                    ws.send_json({'type': 'speech_end', 'turn_id': 'one'})
                    preview = ws.receive_json()
                    self.assertEqual(preview['type'], 'transcript_interim')
                    self.assertEqual(preview['text'], 'Hello.')
                    self.assertEqual(ws.receive_json()['type'], 'turn_committed')
                    self.assertEqual(ws.receive_json()['type'], 'telemetry_stt')
                    self.assertEqual(ws.receive_json()['type'], 'transcript')
                    self.assertEqual(ws.receive_json()['type'], 'turn_complete')
                    ws.send_json({'type': 'speech_end', 'turn_id': 'one'})
                    ws.send_json({'event': 'stop'})
                    self.assertEqual(ws.receive_json()['type'], 'call_ended')
                detail = client.get('/api/calls/' + started['call_id']).json()
                self.assertEqual(len([event for event in detail['events'] if event['kind'] == 'transcript']), 1)
                self.assertFalse(any(event['kind'] == 'transcript_interim' for event in detail['events']))
        self.assertEqual(handled, [('Hello.', 'one')])
        self.assertEqual(keys, ['fake-deepgram-key'])
        self.assertEqual(len(sockets), 1)
        self.assertTrue(sockets[0].closed)


class PhoneStreamingIntegrationTests(unittest.TestCase):
    def test_phone_uses_same_stream_and_closes_on_stop(self):
        import base64
        import copy
        import threading
        from platform_support import platform_client, create_agent
        from app.platform.database import database
        from app.platform.models import Agent, Call
        from app.platform.security import digest
        from twilio.request_validator import RequestValidator
        handled = threading.Event()
        calls, sockets = [], []
        sid, auth = 'AC' + '1' * 32, 'test-auth-only'
        provider_sid = 'CA' + '2' * 32
        base = 'https://hospital.example'

        async def connect(url, key):
            self.assertEqual(key, 'fake-deepgram-key')
            socket = AutoSocket()
            sockets.append(socket)
            return socket

        async def greet(session, turn_id):
            return

        async def handle(session, text, turn_id=None):
            calls.append(text)
            handled.set()

        with platform_client() as client:
            agent = create_agent(client)
            connection = client.post('/api/connections', json={'name': 'Twilio test', 'provider': 'twilio',
                'credentials': {'account_sid': sid, 'auth_token': auth}}).json()
            with database().Session() as db:
                row = db.get(Agent, agent['id'])
                call = Call(workspace_id=row.workspace_id, agent_id=row.id,
                            direction='inbound', connection_id=connection['id'],
                            provider_sid=provider_sid, stream_token_hash=digest('test-stream-token'),
                            config=copy.deepcopy(row.config), knowledge=[], variables={})
                db.add(call)
                db.flush()
                call_id = call.id
                db.commit()
            path = '/ws/telephony/' + call_id
            signature = RequestValidator(auth).compute_signature(base + path, {})
            with patch.dict('os.environ', {'DEEPGRAM_STREAMING_ENABLED': '1', 'SEMANTIC_TURN_ENABLED': '1', 'PUBLIC_BASE_URL': base}), patch(
                'app.pipeline.live_stt.connect_deepgram', connect
            ), patch.object(VoiceSession, 'greet', greet), patch.object(VoiceSession, 'handle_user_speech', handle), patch(
                'app.platform.telephony.update_twilio_call', new_callable=AsyncMock
            ) as update:
                with client.websocket_connect(path, headers={'x-twilio-signature': signature}) as ws:
                    ws.send_json({'event': 'start', 'start': {'callSid': provider_sid, 'streamSid': 'stream',
                        'customParameters': {'token': 'test-stream-token'}}})
                    for frame in [b'\x80' * 160] * 25 + [b'\xff' * 160] * 45:
                        ws.send_json({'event': 'media', 'media': {'payload': base64.b64encode(frame).decode()}})
                    self.assertTrue(handled.wait(3), 'Telephone VAD did not commit the streaming transcript')
                    ws.send_json({'event': 'stop'})
                update.assert_not_awaited()
        self.assertEqual(calls, ['Hello.'])
        self.assertEqual(len(sockets), 1)
        self.assertTrue(sockets[0].closed)
