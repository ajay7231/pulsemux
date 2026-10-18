#!/usr/bin/env python3
"""Matched synthetic HTTP versus semantic-streaming trials; explicit paid --live.

No hospital documents, patient recordings or workspace prompts are read. The
same retained, hashed 8kHz mu-law audio is used by both configurations. VAD
boundaries are scripted; these are server-WAV timings, not caller playback.
"""
import argparse
import asyncio
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker-py'))


def summary(values):
    values = sorted(value for value in values if value is not None)
    return {'n': len(values), 'p50_ms': round(statistics.median(values), 2),
            'p95_ms': round(values[math.ceil(len(values) * .95) - 1], 2)} if values else None


async def run(args):
    from app.web_server import VoiceSession, cancel_turn
    from app.platform.telephony import wav_mulaw
    from app.pipeline.call_audio import mulaw_wav
    import numpy as np
    if not args.live or not all(os.getenv(key) for key in ['DEEPGRAM_API_KEY', 'GROQ_API_KEY']):
        raise RuntimeError('Explicit --live and process-environment Deepgram/Groq keys are required')
    manifest = args.scenarios.read_bytes()
    cases = [case for case in json.loads(manifest)['scenarios'] if case['reference']]
    args.fixtures.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'mode': 'paired_synthetic_release',
              'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'scenario_sha256': hashlib.sha256(manifest).hexdigest(),
              'configuration': {'model': args.model, 'voice': 'af_bella', 'encoding': 'mulaw',
                                'sample_rate': 8000, 'concurrency': 1, 'repetitions': args.repetitions,
                                'http_pause_ms': 800, 'streaming_candidate_ms': 360},
              'fixtures': [], 'rows': [],
              'limitations': ['Generated synthetic speech; not reviewed human/noise recordings.',
                 'Alternate clean/digital 20dB SNR noise; identical hashed audio in both configurations.',
                 'Scripted speech-end boundary after retained audio; segmentation is assessed separately.',
                 'First valid WAV emitted on server excludes browser decode, hardware and carrier playback.',
                 'Uses VoiceSession with a generic acknowledgement prompt; excludes managed hospital RAG.',
                 'Historical Phase 1 audio was not retained; this is a new matched baseline, not an identical historical replay.']}
    generator = VoiceSession(None)
    generator.keys_managed = True
    generator.provider_keys = {}
    fixtures = {}
    for index, case in enumerate(cases):
        clean_path = args.fixtures / (case['id'] + '-clean.wav')
        if not clean_path.exists():
            source = await generator.synthesize_audio(case['reference'].replace('...', ''), 'fixture')
            if not source:
                raise RuntimeError('Local fixture synthesis failed')
            clean_path.write_bytes(mulaw_wav(wav_mulaw(source)))
        clean = clean_path.read_bytes()
        for variant in ['clean', 'digital_noise_20db']:
            path = args.fixtures / (case['id'] + '-' + variant + '.wav')
            if not path.exists():
                with wave.open(io.BytesIO(clean)) as reader:
                    samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype='<i2').astype(np.float64)
                rms = float(np.sqrt(np.mean(samples ** 2)))
                noise = np.random.default_rng(1000 + index).normal(0, rms / 10, len(samples))
                output = io.BytesIO()
                with wave.open(output, 'wb') as writer:
                    writer.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    writer.writeframes(np.clip(samples + noise, -32768, 32767).astype('<i2').tobytes())
                path.write_bytes(mulaw_wav(wav_mulaw(base64.b64encode(output.getvalue()).decode())))
            wav = path.read_bytes()
            payload = wav_mulaw(base64.b64encode(wav).decode())
            payload = payload.ljust((len(payload) + 159) // 160 * 160, b'\xff')
            # Both inputs are exactly the decoded version of these transmitted bytes.
            wav = mulaw_wav(payload)
            path.write_bytes(wav)
            fixtures[(case['id'], variant)] = (wav, payload)
            report['fixtures'].append({'scenario': case['id'], 'variant': variant,
                'file': path.name, 'sha256': hashlib.sha256(wav).hexdigest(),
                'audio_seconds': len(payload) / 8000})

    class Observer:
        def __init__(self):
            self.speech_end = self.commit = self.first_text = self.first_audio = None
            self.transcript, self.errors, self.commits = '', [], 0
            self.completed = False

        async def send_text(self, payload):
            event = json.loads(payload)
            now = time.perf_counter()
            if event['type'] == 'turn_committed':
                self.commits += 1
                self.commit = now
            elif event['type'] == 'transcript':
                self.transcript = event['text']
            elif event['type'] == 'token' and event.get('delta') and self.first_text is None:
                self.first_text = now
            elif event['type'] == 'audio_clause' and self.first_audio is None:
                with wave.open(io.BytesIO(base64.b64decode(event['audio_b64']))) as reader:
                    if not reader.getnframes():
                        raise RuntimeError('Empty response WAV')
                self.first_audio = now
            elif event['type'] in {'error', 'stt_empty', 'tts_warning', 'audio_unavailable'}:
                self.errors.append(event['type'])
            elif event['type'] == 'turn_complete':
                self.completed = True

    for repetition in range(args.repetitions):
        variant = 'clean' if repetition % 2 == 0 else 'digital_noise_20db'
        for case in cases:
            wav, payload = fixtures[(case['id'], variant)]
            modes = ['http_fixed', 'streaming_semantic']
            if repetition % 2:
                modes.reverse()
            for mode in modes:
                observer = Observer()
                trial = VoiceSession(observer)
                trial.keys_managed = True
                trial.provider_keys = {'stt': os.environ['DEEPGRAM_API_KEY'], 'llm': os.environ['GROQ_API_KEY']}
                trial.llm_model = args.model
                trial.system_prompt = ('Synthetic transport evaluation. Reply with one short acknowledgement sentence. '
                                       'Do not provide clinical advice or claim that any action was performed.')
                row = {'scenario': case['id'], 'repetition': repetition, 'variant': variant, 'pipeline': mode,
                       'reference': case['reference'], 'audio_sha256': hashlib.sha256(wav).hexdigest()}
                try:
                    async with asyncio.timeout(50):
                        if mode == 'http_fixed':
                            observer.speech_end = time.perf_counter()
                            await asyncio.sleep(.8)
                            observer.commit = time.perf_counter()
                            observer.commits = 1
                            recognized = await trial.transcribe_audio(wav, 'audio/wav')
                            if recognized:
                                await trial.handle_user_speech(recognized, 'release')
                            else:
                                observer.errors.append('empty_transcript')
                        else:
                            await trial.start_recognition()
                            trial.begin_recognition('release')
                            deadline = time.perf_counter()
                            async def feed(frame):
                                nonlocal deadline
                                await trial.feed_recognition(frame)
                                deadline += .02
                                await asyncio.sleep(max(0, deadline - time.perf_counter()))
                            for offset in range(0, len(payload), 160):
                                await feed(payload[offset:offset + 160])
                            observer.speech_end = time.perf_counter()
                            for _ in range(18):
                                await feed(b'\xff' * 160)
                            await trial.pause_recognition('release', 360)
                            while not observer.completed and not trial.recognition_failed:
                                await feed(b'\xff' * 160)
                except Exception as exc:
                    observer.errors.append(type(exc).__name__)
                finally:
                    await cancel_turn(trial)
                    stream, policy = trial.live_stt, trial.turn_completion
                    await trial.close_recognition()
                def elapsed(end, start):
                    return round((end - start) * 1000, 2) if end is not None and start is not None else None
                row.update({'transcript': observer.transcript, 'completed': observer.completed,
                    'errors': observer.errors, 'commit_count': observer.commits,
                    'speech_end_to_commit_ms': elapsed(observer.commit, observer.speech_end),
                    'speech_end_to_first_text_ms': elapsed(observer.first_text, observer.speech_end),
                    'speech_end_to_first_wav_ms': elapsed(observer.first_audio, observer.speech_end),
                    'commit_to_first_wav_ms': elapsed(observer.first_audio, observer.commit),
                    'pending_tasks_after_close': len(stream.tasks) + len(stream.collectors) + (len(policy.tasks) if policy else 0) if stream else 0})
                report['rows'].append(row)
                args.output.write_text(json.dumps(report, indent=2) + '\n')
                print('Completed ' + mode + ' ' + case['id'] + ' ' + str(repetition), flush=True)
    report['summary'] = {}
    for mode in ['http_fixed', 'streaming_semantic']:
        rows = [row for row in report['rows'] if row['pipeline'] == mode]
        report['summary'][mode] = {'trials': len(rows),
            'failed_trials': sum(not row['completed'] or bool(row['errors']) for row in rows),
            **{key: summary([row[key] for row in rows]) for key in [
                'speech_end_to_first_text_ms', 'speech_end_to_first_wav_ms', 'commit_to_first_wav_ms']}}
    args.output.write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', required=True)
    parser.add_argument('--repetitions', type=int, default=4, choices=range(1, 9))
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'benchmarks/voice/scenarios.json')
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
