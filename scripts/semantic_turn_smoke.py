#!/usr/bin/env python3
"""Explicit live Deepgram test with local synthetic speech; no LLM or hospital KB.

DEEPGRAM_API_KEY is required. Boundaries are scripted, not microphone VAD.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker-py'))


async def run(output):
    from app.web_server import VoiceSession
    from app.platform.telephony import wav_mulaw
    key = os.environ.get('DEEPGRAM_API_KEY')
    if not key:
        raise RuntimeError('A Deepgram key is required for this explicitly live synthetic test')
    report = {'mode': 'live_semantic_synthetic', 'rows': [],
              'limitations': ['Two synthetic calls, not a latency or accuracy benchmark.',
                              'Scripted VAD boundaries; no microphone, LLM, retrieval or carrier call.']}
    for name, parts in [('complete_thought', ['Please confirm my appointment.']),
                        ('unfinished_with_1000ms_gap', ['I have been feeling', 'dizzy since yesterday.'])]:
        events, handled = [], []
        class Sink:
            async def send_text(self, payload):
                value = json.loads(payload)
                if value['type'] != 'transcript_interim':
                    events.append((time.perf_counter(), value))
        session = VoiceSession(Sink())
        session.keys_managed = True
        session.provider_keys = {'stt': key}
        async def handle(text, turn_id):
            handled.append({'text': text, 'turn_id': turn_id})
        session.handle_user_speech = handle
        payloads = []
        for part in parts:
            payload = wav_mulaw(await session.synthesize_audio(part, 'synthetic'))
            if not payload:
                raise RuntimeError('Synthetic audio generation failed')
            payloads.append(payload.ljust((len(payload) + 159) // 160 * 160, b'\xff'))
        deadline = time.perf_counter()
        async def feed(payload):
            nonlocal deadline
            for offset in range(0, len(payload), 160):
                await session.feed_recognition(payload[offset:offset + 160])
                deadline += .02
                await asyncio.sleep(max(0, deadline - time.perf_counter()))
        stream, policy = None, None
        partial_commits = 0
        try:
            await session.start_recognition()
            stream, policy = session.live_stt, session.turn_completion
            if policy is None:
                raise RuntimeError('Enable SEMANTIC_TURN_ENABLED for this test')
            deadline = time.perf_counter()
            for index, payload in enumerate(payloads):
                turn = name + '-' + str(index)
                session.begin_recognition(turn)
                await feed(payload)
                speech_end = time.perf_counter()
                await feed(b'\xff' * 160 * 18)
                await session.pause_recognition(turn, 360)
                if index < len(payloads) - 1:
                    await feed(b'\xff' * 160 * 32)
                    partial_commits = sum(value['type'] == 'turn_committed' for _, value in events)
                else:
                    await feed(b'\xff' * 160 * 60)
            if session.active_turn_task:
                await asyncio.wait_for(session.active_turn_task, 4)
            commits = [(at, value) for at, value in events if value['type'] == 'turn_committed']
            row = {'scenario': name, 'responses': handled, 'commit_count': len(commits),
                   'commits_during_incomplete_gap': partial_commits,
                   'speech_boundary_to_commit_ms': round((commits[0][0] - speech_end) * 1000, 1) if commits else None,
                   'recognition_failed': session.recognition_failed}
            report['rows'].append(row)
            if session.recognition_failed or len(handled) != 1 or len(commits) != 1 or partial_commits:
                raise RuntimeError('Synthetic semantic call did not meet acceptance criteria')
            if len(parts) == 2 and not all(word in handled[0]['text'].lower() for word in ['feeling', 'dizzy']):
                raise RuntimeError('Continuation text was lost')
        finally:
            if session.active_turn_task and not session.active_turn_task.done():
                session.active_turn_task.cancel()
                await asyncio.gather(session.active_turn_task, return_exceptions=True)
            await session.close_recognition()
            if report['rows']:
                report['rows'][-1]['pending_tasks_after_close'] = len(stream.tasks) + len(stream.collectors) + len(policy.tasks) if stream and policy else None
            output.write_text(json.dumps(report, indent=2) + '\n')
        print('Passed synthetic semantic scenario: ' + name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
