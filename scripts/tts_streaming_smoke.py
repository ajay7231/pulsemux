#!/usr/bin/env python3
"""Explicit live Deepgram transport smoke. Synthetic text; never saves audio or keys."""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import time

from app.web_server import VoiceSession


async def run():
    key = os.getenv('DEEPGRAM_API_KEY')
    if not key:
        raise RuntimeError('DEEPGRAM_API_KEY must be supplied in the process environment')
    rows = []
    for phone in (False, True):
        started, first, frames, byte_count = time.perf_counter(), None, 0, 0
        class Sink:
            phone_audio = phone
            async def send_text(self, value):
                nonlocal first, frames, byte_count
                event = json.loads(value)
                if event['type'] != 'audio_chunk':
                    raise RuntimeError('Streaming test received a fallback or error')
                expected_encoding, rate = ('mulaw', 8000) if phone else ('linear16', 24000)
                if event['encoding'] != expected_encoding or event['sample_rate'] != rate:
                    raise RuntimeError('Unexpected audio format')
                chunk = base64.b64decode(event['audio_b64'], validate=True)
                if not 0 < len(chunk) <= (160 if phone else 960):
                    raise RuntimeError('Unexpected frame size')
                if not phone and len(chunk) % 2:
                    raise RuntimeError('Incomplete PCM sample')
                if first is None:
                    first = time.perf_counter()
                frames += 1
                byte_count += len(chunk)
        session = VoiceSession(Sink())
        session.keys_managed = True
        session.provider_keys = {'tts': key}
        session.tts_engine, session.voice_id = 'deepgram', 'aura-2-thalia-en'
        try:
            async with asyncio.timeout(30):
                await session.speak('This is a streaming audio test. Please confirm you can hear this response.', 'synthetic')
                finished = time.perf_counter()
                if first is None or frames < 2 or first >= finished:
                    raise RuntimeError('Audio did not arrive incrementally')
        finally:
            await session.close_recognition()
        rows.append({'transport': 'phone_adapter_input' if phone else 'browser_websocket_output',
                     'encoding': 'mulaw' if phone else 'linear16', 'sample_rate':8000 if phone else 24000,
                     'frames':frames, 'audio_bytes':byte_count,
                     'first_chunk_ms':round((first-started)*1000,1),
                     'complete_ms':round((finished-started)*1000,1),
                     'client_closed':session.speech_output.client is None})
    return {'mode':'live_synthetic_tts', 'voice':'aura-2-thalia-en', 'rows':rows,
            'limitations':['Two synthetic provider requests, not a latency benchmark.',
                           'Server-side delivery only; no acoustic or carrier playback measurement.',
                           'The phone sink validates format, not realtime carrier delivery.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Allow two billable synthetic TTS requests')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required to contact Deepgram')
    result = asyncio.run(run())
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end='')
