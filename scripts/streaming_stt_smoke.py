#!/usr/bin/env python3
"""Explicit live smoke test: generated synthetic audio to Deepgram, no LLM or KB."""
import argparse
import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker-py'))


async def run(args):
    from app.web_server import VoiceSession
    from app.pipeline.live_stt import DeepgramCallStream, connect_deepgram
    from app.platform.telephony import wav_mulaw
    from app.pipeline.call_audio import mulaw_wav
    key = os.environ.get('DEEPGRAM_API_KEY')
    if not key:
        raise RuntimeError('DEEPGRAM_API_KEY is required; only synthetic fixtures are sent')
    fixture_session = VoiceSession(None)
    fixture_session.keys_managed = True
    fixture_session.provider_keys = {}
    interim = []
    failures = []
    connections = 0

    async def partial(turn, text):
        interim.append(turn)

    async def fail():
        failures.append('recognition_failure')

    async def connect(url, credential):
        nonlocal connections
        connections += 1
        return await connect_deepgram(url, credential)

    stream = DeepgramCallStream(key, partial, fail, connector=connect)
    report = {'mode': 'live_streaming_synthetic', 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'configuration': {'model': 'nova-3', 'encoding': 'mulaw', 'sample_rate': 8000,
                                'end_pause_ms': 800, 'concurrency': 1},
              'source_sha256': hashlib.sha256(inspect.getsource(DeepgramCallStream).encode()).hexdigest(), 'rows': []}
    scenarios = json.loads(args.scenarios.read_text())['scenarios']
    args.audio_dir.mkdir(parents=True, exist_ok=True)
    try:
        await stream.start()
        for case in scenarios:
            if case['id'] not in {'complete_thought', 'medication_names', 'numbers_and_units'}:
                continue
            audio = await fixture_session.synthesize_audio(case['reference'], 'fixture')
            if not audio:
                raise RuntimeError('Local synthetic audio generation failed')
            payload = wav_mulaw(audio)
            payload = payload.ljust(((len(payload) + 159) // 160) * 160, b'\xff')
            synthetic_wav = mulaw_wav(payload)
            (args.audio_dir / (case['id'] + '.wav')).write_bytes(synthetic_wav)
            stream.begin_turn(case['id'])
            frames = [b'\xff' * 160] * 30 + [payload[i:i + 160] for i in range(0, len(payload), 160)] + [b'\xff' * 160] * 40
            deadline = time.perf_counter()
            for frame in frames:
                stream.feed(frame)
                deadline += .02
                await asyncio.sleep(max(0, deadline - time.perf_counter()))
            began = time.perf_counter()
            text = await stream.end_turn(case['id'], pause_ms=800)
            report['rows'].append({'scenario': case['id'], 'reference': case['reference'], 'transcript': text,
                'critical_terms': case['critical_terms'], 'audio_sha256': hashlib.sha256(synthetic_wav).hexdigest(),
                'boundary_to_final_ms': round((time.perf_counter() - began) * 1000, 2),
                'interim_events': interim.count(case['id'])})
            print('Completed synthetic streaming scenario: ' + case['id'], flush=True)
    finally:
        await stream.close()
        report.update({'connections_opened': connections, 'failure_events': failures,
                       'closed': stream.closed, 'pending_tasks': len(stream.tasks) + len(stream.collectors),
                       'limitations': ['Three synthetic utterances; not an accuracy benchmark.',
                           'Boundary-to-final wait excludes speech duration and the preceding 800ms pause.',
                           'No LLM, retrieval, clinical reasoning, or browser/carrier playback was tested.',
                           'Retained synthetic WAVs are 8kHz decoded mu-law; compare their hashes when replaying.']})
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    if connections != 1 or failures or len(report['rows']) != 3 or any(not row['transcript'] for row in report['rows']):
        raise RuntimeError('Streaming provider smoke test did not meet acceptance conditions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'benchmarks/voice/scenarios.json')
    parser.add_argument('--audio-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
