#!/usr/bin/env python3
"""Compare actual browser VAD and Python completion rules in virtual time.

Transcript cues are scripted from synthetic references, not recognized audio.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker-py'))
sys.path.insert(0, str(ROOT / 'worker-py/tests'))
from app.pipeline.turn_completion import SemanticTurnCompletion
from test_turn_completion import VirtualClock


async def run():
    source = (ROOT / 'benchmarks/voice/scenarios.json').read_bytes()
    manifest = json.loads(source)
    def replay(*extra):
        return json.loads(subprocess.check_output(['node', str(ROOT / 'scripts/voice_turn_baseline.cjs'), *extra], cwd=ROOT))
    baseline, candidates = replay(), replay('--pause-ms', '350')
    rows = []
    for case, vad in zip(manifest['scenarios'], candidates['scenarios']):
        clock, commits, failures = VirtualClock(), [], []
        async def commit(turn, pause_ms, forced):
            commits.append({'at_ms': round(clock() * 1000), 'forced': forced, 'pause_ms': pause_ms})
        async def failure():
            failures.append('completion_failure')
        policy = SemanticTurnCompletion(commit, failure, clock=clock, sleep=clock.sleep)
        events = {event['at_ms']: event['event'] for event in vad['events']}
        elapsed, turn, last_voiced_end = 0, 0, None
        segment_start, incomplete_range = 0, None
        for index, (duration, rms) in enumerate(case['segments']):
            if index == case.get('incomplete_pause_index'):
                incomplete_range = (segment_start, segment_start + duration)
            segment_start += duration
            if rms >= .08:
                last_voiced_end = segment_start
            for _ in range(duration // 20):
                elapsed += 20
                await clock.advance(20)
                event = events.get(elapsed)
                if event == 'start':
                    turn += 1
                    policy.start(str(turn))
                elif event == 'end':
                    if index == case.get('incomplete_pause_index'):
                        text = case['reference'].split('...')[0].strip() + '.'
                    elif case['id'] == 'ordinary_mid_sentence_pause' and index == 2:
                        text = 'I called yesterday, and'
                    else:
                        text = case['reference'].replace('...', '')
                    policy.observe(str(turn), text, is_final=True)
                    await policy.pause(str(turn), 0 if rms >= .08 else 360, force=rms >= .08)
                    for _ in range(4):
                        await asyncio.sleep(0)
        await clock.advance(1500)
        await policy.close()
        last = next((entry for entry in commits if last_voiced_end is not None and entry['at_ms'] >= last_voiced_end), None)
        rows.append({'scenario': case['id'], 'baseline_vad_turns': baseline['scenarios'][len(rows)]['detected_turns'],
            'semantic_commits': len(commits), 'expected_turns': case['expected_turns'],
            'segmentation_matches_target': len(commits) == case['expected_turns'],
            'premature_commit_in_unfinished_pause': any(incomplete_range[0] < entry['at_ms'] <= incomplete_range[1] for entry in commits) if incomplete_range else None,
            'final_speech_end_to_commit_ms': last['at_ms'] - last_voiced_end if last else None,
            'commits': commits, 'failures': failures, 'pending_tasks_after_close': len(policy.tasks)})
    return {'mode': 'virtual_vad_plus_scripted_transcript_replay', 'scenario_sha256': hashlib.sha256(source).hexdigest(),
        'baseline_matching_scenarios': baseline['matching_segmentation_count'],
        'semantic_matching_scenarios': sum(row['segmentation_matches_target'] for row in rows),
        'rows': rows, 'limitations': ['Virtual 20ms frames, not wall-clock voice latency.',
          'Transcript completeness cues are supplied; this does not measure ASR or clinical accuracy.',
          'Energy VAD still triggers on the non-speech burst; this is deliberately retained as a failing scenario.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(asyncio.run(run()), indent=2) + '\n')
