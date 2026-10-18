#!/usr/bin/env python3
"""Offline concurrent lifecycle validation; provider protocol is emulated.

Not an ASR, provider concurrency, throughput, memory-per-call or latency SLA test.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker-py'))


class Provider:
    def __init__(self, phrase):
        self.phrase, self.bytes, self.closed, self.keepalives = phrase, 0, False, 0
        self.incoming = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.incoming.get()
        if item is None:
            raise StopAsyncIteration
        return json.dumps(item)

    async def send(self, payload):
        if isinstance(payload, bytes):
            self.bytes += len(payload)
        elif json.loads(payload)['type'] == 'KeepAlive':
            self.keepalives += 1
        elif json.loads(payload)['type'] == 'Finalize':
            await self.incoming.put({'type': 'Results', 'is_final': True, 'start': 0,
                'duration': self.bytes / 8000, 'channel': {'alternatives': [{
                    'transcript': self.phrase, 'words': [{'word': self.phrase, 'start': .1, 'end': .3}]}]}})

    async def close(self):
        self.closed = True
        await self.incoming.put(None)


async def run(args):
    from app.pipeline.live_stt import DeepgramCallStream
    from app.pipeline.turn_completion import SemanticTurnCompletion
    from app.web_server import VoiceSession, cancel_turn
    semaphore, rows = asyncio.Semaphore(args.concurrency), []
    active, peak = 0, 0
    before = len(asyncio.all_tasks())
    class Sink:
        async def send_text(self, value):
            pass
    async def one(index):
        nonlocal active, peak
        async with semaphore:
            active += 1
            peak = max(peak, active)
            case = ['complete', 'provider_disconnect', 'hangup_during_pending', 'idle_keepalive'][index % 4]
            phrase = 'synthetic-call-' + str(index) + '.'
            provider = Provider('and' if case == 'hangup_during_pending' else phrase)
            session = VoiceSession(Sink())
            done, outputs = asyncio.Event(), []
            async def handle(text, turn_id):
                outputs.append(text)
                done.set()
            session.handle_user_speech = handle
            async def connector(url, key):
                return provider
            stream = DeepgramCallStream('fake-offline-key', session.recognition_interim,
                session.recognition_failure, connector=connector, keepalive_seconds=.01)
            policy = SemanticTurnCompletion(session.commit_semantic_turn, session.recognition_failure)
            stream.on_result = policy.observe
            session.live_stt, session.turn_completion = stream, policy
            backlog = 0
            try:
                await stream.start()
                if case == 'idle_keepalive':
                    await asyncio.sleep(.06)  # Accelerated heartbeat cycles, not hours of silence.
                else:
                    session.begin_recognition('call-' + str(index))
                    for _ in range(65):
                        stream.feed(b'\xff' * 160)
                        backlog = max(backlog, stream.queue.qsize())
                    await stream.queue.join()
                    if case == 'provider_disconnect':
                        await provider.close()
                        for _ in range(10):
                            await asyncio.sleep(0)
                    else:
                        await session.pause_recognition('call-' + str(index), 360)
                        if case == 'complete':
                            await asyncio.wait_for(done.wait(), 2)
                            await session.pause_recognition('call-' + str(index), 360)
            finally:
                await cancel_turn(session)
                await session.close_recognition()
                active -= 1
            valid = (outputs == [phrase] if case == 'complete' else not outputs)
            valid = valid and provider.closed and not stream.tasks and not stream.collectors and not policy.tasks
            if case == 'provider_disconnect':
                valid = valid and session.recognition_failed
            if case == 'idle_keepalive':
                valid = valid and provider.keepalives > 0 and not session.recognition_failed
            rows.append({'case': case, 'index': index, 'passed': valid,
                         'responses': len(outputs), 'peak_backlog_frames': backlog,
                         'provider_closed': provider.closed, 'pending_tasks': len(stream.tasks) + len(stream.collectors) + len(policy.tasks)})
    await asyncio.gather(*(one(index) for index in range(args.calls)))
    await asyncio.sleep(0)
    report = {'mode': 'offline_emulated_provider_lifecycle', 'calls': args.calls,
              'concurrency_limit': args.concurrency, 'peak_active_sessions': peak,
              'tasks_before': before, 'tasks_after': len(asyncio.all_tasks()),
              'failed_cases': sum(not row['passed'] for row in rows), 'rows': rows,
              'limitations': ['No external provider, microphone, LLM, RAG or carrier traffic.',
                 'Idle heartbeat time is accelerated; not an endurance or provider billing test.',
                 'Does not establish the original Go gateway concurrency, memory, jitter or latency SLAs.']}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if report['failed_cases'] or report['tasks_before'] != report['tasks_after']:
        raise RuntimeError('Concurrent lifecycle validation failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls', type=int, default=80, choices=range(4, 201))
    parser.add_argument('--concurrency', type=int, default=20, choices=range(1, 51))
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
