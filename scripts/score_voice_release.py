#!/usr/bin/env python3
"""Score paired reports without dropping failed/empty trials or repairing facts."""
import argparse
import hashlib
import json
from pathlib import Path
from score_voice_baseline import score

ROOT = Path(__file__).resolve().parents[1]


def evaluate(report, manifest, policy):
    scores = {}
    for mode in ['http_fixed', 'streaming_semantic']:
        scores[mode] = score({'rows': [row for row in report['rows'] if row['pipeline'] == mode]}, manifest, policy)
    pairs = {}
    for row in report['rows']:
        pairs.setdefault((row['scenario'], row['repetition']), {})[row['pipeline']] = row
    exact_pairs = len(pairs) > 0 and len(report['rows']) == 2 * len(pairs) and all(set(pair) == {'http_fixed', 'streaming_semantic'} and
        pair['http_fixed']['audio_sha256'] == pair['streaming_semantic']['audio_sha256'] for pair in pairs.values())
    old, new = scores['http_fixed'], scores['streaming_semantic']
    gates = {
        'identical_audio_pairs': exact_pairs,
        'minimum_30_trials_per_configuration': min(old['trials'], new['trials']) >= 30,
        'all_turns_complete_without_errors': all(row.get('completed') and not row.get('errors') for row in report['rows']),
        'exactly_one_commit_per_trial': all(row.get('commit_count') == 1 for row in report['rows']),
        'no_pending_tasks': all(row.get('pending_tasks_after_close') == 0 for row in report['rows']),
        'no_normalized_wer_regression': new['corpus_wer'] is not None and old['corpus_wer'] is not None and new['corpus_wer'] <= old['corpus_wer'],
        'all_expected_critical_terms_present': new['trials_with_missing_critical_terms'] == 0,
        'no_unresolved_date_format_review': new['trials_requiring_format_review'] == 0,
    }
    return {'scores': scores, 'gates': gates, 'automated_gates_pass': all(gates.values()),
        'limitations': ['Critical-term presence does not prove absence of conflicting facts or clinical-answer correctness.',
            'Do not mark release ready from this report alone: human/noise, microphone playback and transport review are separate.',
            'Numeric dates remain unresolved; locale is not inferred or silently normalized.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'benchmarks/voice/scenarios.json')
    parser.add_argument('--normalization', type=Path, default=ROOT / 'benchmarks/voice/normalization.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, manifest, policy = args.report.read_bytes(), args.scenarios.read_bytes(), args.normalization.read_bytes()
    report = json.loads(source)
    if report['scenario_sha256'] != hashlib.sha256(manifest).hexdigest():
        parser.error('Scenario manifest does not match the paired run')
    result = evaluate(report, json.loads(manifest), json.loads(policy))
    result.update({'report_sha256': hashlib.sha256(source).hexdigest(), 'normalization_sha256': hashlib.sha256(policy).hexdigest()})
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['gates'], indent=2))
