#!/usr/bin/env python3
"""Measure local TTS, or explicitly opt into synthetic provider trials.

Default mode makes no provider requests. Live mode uses environment keys only,
never the workspace database, documents, saved connections, or patient audio.
"""
import argparse
import asyncio
import base64
import hashlib
import io
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker-py"))


def summary(values):
    if not values:
        return None
    values = sorted(values)
    return {"n": len(values), "p50_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[max(0, math.ceil(len(values) * .95) - 1)], 2)}


def valid_wav(value):
    if not value:
        raise RuntimeError("Local Kokoro did not produce audio; no simulated fallback is permitted")
    audio = base64.b64decode(value, validate=True)
    with wave.open(io.BytesIO(audio)) as wav:
        if wav.getnframes() == 0:
            raise RuntimeError("Empty WAV")
    return audio


async def run(args):
    from app.web_server import VoiceSession

    class Observer:
        def __init__(self):
            self.started = time.perf_counter()
            self.first_text = self.first_audio = None
            self.errors = []
            self.completed = False

        async def send_text(self, payload):
            data = json.loads(payload)
            elapsed = (time.perf_counter() - self.started) * 1000
            if data['type'] == 'token' and data.get('delta') and self.first_text is None:
                self.first_text = elapsed
            if data['type'] == 'audio_clause' and self.first_audio is None:
                valid_wav(data['audio_b64'])
                self.first_audio = elapsed
            if data['type'] in {'error', 'stt_empty', 'tts_warning', 'audio_unavailable'}:
                # Store event categories, not provider response bodies or transcript content.
                self.errors.append(data['type'])
            if data['type'] == 'turn_complete':
                self.completed = True

    report = {"schema_version": 1, "mode": "live_synthetic" if args.live else "local_tts_only",
              "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              "clock": "time.perf_counter", "python": sys.version.split()[0],
              "voice_session_sha256": hashlib.sha256(inspect.getsource(VoiceSession).encode()).hexdigest(), "rows": []}
    observer = Observer()
    session = VoiceSession(observer)
    session.keys_managed = True
    session.provider_keys = {}  # Never fall through to environment providers in local mode.
    session.tts_engine = 'kokoro'
    session.voice_id = 'af_bella'
    report['configuration'] = {'tts_engine': 'kokoro', 'voice': session.voice_id, 'repetitions': args.repetitions}
    if not args.live:
        for i in range(args.repetitions + 1):
            started = time.perf_counter()
            audio = valid_wav(await session.synthesize_audio('This is a synthetic voice quality test.', 'baseline'))
            elapsed = (time.perf_counter() - started) * 1000
            report['rows'].append({'sample': i, 'temperature': 'cold' if i == 0 else 'warm',
                                   'wav_generation_ms': round(elapsed, 2), 'wav_bytes': len(audio)})
        report['warm_tts'] = summary([r['wav_generation_ms'] for r in report['rows'] if r['temperature'] == 'warm'])
        report['unmeasured'] = ['speech recognition', 'first response text', 'speech-end to first audible output', 'browser/carrier playback', 'recognition accuracy']
        report['limitations'] = ['Local clause WAV generation only, not end-to-end voice latency.', 'Cold means the first invocation in this process; host disk caches may already be warm.']
        return report

    deepgram, groq = os.getenv('DEEPGRAM_API_KEY'), os.getenv('GROQ_API_KEY')
    if not deepgram or not groq:
        raise RuntimeError('Live mode requires DEEPGRAM_API_KEY and GROQ_API_KEY in the process environment')
    scenario_bytes = args.scenarios.read_bytes()
    scenarios = json.loads(scenario_bytes)['scenarios']
    report['scenario_sha256'] = hashlib.sha256(scenario_bytes).hexdigest()
    report['configuration'].update({'stt_engine': 'deepgram', 'llm_model': args.model})
    for case in scenarios:
        if not case['reference']:
            continue
        # All provider audio is generated here from the checked-in synthetic references.
        fixture = valid_wav(await session.synthesize_audio(case['reference'].replace('...', ''), 'fixture'))
        for repetition in range(args.repetitions):
            observer = Observer()
            trial = VoiceSession(observer)
            trial.keys_managed = True
            trial.provider_keys = {'stt': deepgram, 'llm': groq}
            trial.stt_engine = 'deepgram'
            trial.llm_model = args.model
            trial.system_prompt = ('This is a synthetic voice transport evaluation. Reply in one short sentence acknowledging '
                                   'the request. Do not provide clinical advice or claim that any action was performed.')
            try:
                async with asyncio.timeout(45):
                    text = await trial.transcribe_audio(fixture, 'audio/wav')
                    stt_ms = (time.perf_counter() - observer.started) * 1000
                    if text:
                        await trial.handle_user_speech(text, 'baseline')
                    else:
                        observer.errors.append('empty_transcript')
                report['rows'].append({'scenario': case['id'], 'repetition': repetition,
                    'reference': case['reference'], 'transcript': text, 'critical_terms': case['critical_terms'],
                    'stt_ms': round(stt_ms, 2),
                    'first_response_text_ms': round(observer.first_text, 2) if observer.first_text is not None else None,
                    'first_playable_wav_ms': round(observer.first_audio, 2) if observer.first_audio is not None else None,
                    'completed': observer.completed, 'errors': observer.errors})
            except Exception as exc:
                report['rows'].append({'scenario': case['id'], 'repetition': repetition,
                    'completed': False, 'errors': [type(exc).__name__]})
    report['summary'] = {key: summary([r[key] for r in report['rows'] if r.get(key) is not None])
                         for key in ['stt_ms', 'first_response_text_ms', 'first_playable_wav_ms']}
    report['failed_trials'] = sum(not r['completed'] or bool(r['errors']) for r in report['rows'])
    report['limitations'] = ['Synthetic Kokoro speech; no microphone, room acoustics, or actual patient recordings.',
        'Starts at completed-WAV submission; excludes VAD waiting, capture, retrieval, browser decode/playback, and carrier delay.',
        'Uses VoiceSession directly, not the managed dashboard transport or hospital knowledge. Not a clinical accuracy test.',
        'WAV receipt means playable audio available on server, not audio heard by caller.',
        'Sample order includes provider cold and warm behavior; small-sample percentiles are descriptive only.',
        'References require human normalization review for numbers, units and dates; no automatic clinical accuracy verdict.']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly send generated synthetic speech to Deepgram and recognized text to Groq; uses paid APIs')
    parser.add_argument('--model', default='openai/gpt-oss-120b')
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'benchmarks/voice/scenarios.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.live and sys.version_info < (3, 11):
        parser.error('Live trials require Python 3.11 or later; use the Python 3.12 baseline image')
    if args.repetitions < 1 or args.repetitions > 20:
        parser.error('--repetitions must be between 1 and 20')
    report = asyncio.run(run(args))
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"Saved {report['mode']} baseline to {args.output}")


if __name__ == '__main__':
    main()
