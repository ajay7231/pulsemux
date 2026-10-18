#!/usr/bin/env python3
"""Explicit live synthetic silence/keepalive/disconnect check; no microphone/LLM."""
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
    from app.pipeline.live_stt import DeepgramCallStream
    if not os.getenv('DEEPGRAM_API_KEY'):
        raise RuntimeError('Explicit Deepgram process-environment key required')
    failures, interims = [], []
    async def interim(turn, text):
        interims.append(turn)
    async def failure():
        failures.append(time.perf_counter())
    stream = DeepgramCallStream(os.environ['DEEPGRAM_API_KEY'], interim, failure)
    began = time.perf_counter()
    try:
        await stream.start()
        deadline = time.perf_counter()
        for _ in range(1500):  # 30 real seconds of generated digital silence.
            stream.feed(b'\xff' * 160)
            deadline += .02
            await asyncio.sleep(max(0, deadline - time.perf_counter()))
        await asyncio.sleep(15)  # No audio: production 3-second KeepAlive must preserve the socket.
        healthy_before_disconnect = not stream.failed
        await stream.ws.close()  # Deliberately emulate upstream closure, not caller teardown.
        for _ in range(20):
            if stream.failed:
                break
            await asyncio.sleep(.01)
    finally:
        await stream.close()
    report = {'mode': 'live_generated_silence_keepalive_disconnect',
        'silence_seconds': 30, 'no_audio_keepalive_seconds': 15,
        'wall_seconds': round(time.perf_counter() - began, 2),
        'healthy_before_injected_disconnect': healthy_before_disconnect,
        'failure_callback_count': len(failures), 'interim_events': len(interims),
        'pending_tasks_after_close': len(stream.tasks) + len(stream.collectors),
        'limitations': ['One provider connection; no microphone, clinical content, LLM or carrier.',
                        'Disconnect is deliberately injected; this is not a natural outage observation.']}
    output.write_text(json.dumps(report, indent=2) + '\n')
    if not healthy_before_disconnect or len(failures) != 1 or interims or stream.tasks:
        raise RuntimeError('Live silence/disconnect acceptance failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
