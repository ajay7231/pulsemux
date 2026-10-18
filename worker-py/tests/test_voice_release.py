"""Release gates must retain errors and detect mismatched input or regressions."""
import sys
from pathlib import Path
import unittest

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'scripts/score_voice_release.py').exists())
sys.path.insert(0, str(ROOT / 'scripts'))
from score_voice_release import evaluate


class ReleaseGateTests(unittest.TestCase):
    def fixture(self):
        case = {'id': 'dose', 'reference': 'Brilinta 90 mg not 95 mg', 'critical_terms': ['Brilinta', '90', 'not', '95']}
        rows = [{'scenario': 'dose', 'repetition': index, 'pipeline': mode,
            'audio_sha256': 'same', 'transcript': case['reference'], 'completed': True,
            'errors': [], 'commit_count': 1, 'pending_tasks_after_close': 0}
            for index in range(30) for mode in ['http_fixed', 'streaming_semantic']]
        return {'rows': rows}, {'scenarios': [case]}, {'version': 'test', 'replacements': []}

    def test_exact_matched_success_passes_automated_gates(self):
        self.assertTrue(evaluate(*self.fixture())['automated_gates_pass'])

    def test_dropped_negation_and_wrong_drug_fail_accuracy_gate(self):
        report, cases, policy = self.fixture()
        report['rows'][1]['transcript'] = 'aspirin 90 mg 95 mg'
        result = evaluate(report, cases, policy)
        self.assertFalse(result['gates']['no_normalized_wer_regression'])
        self.assertFalse(result['gates']['all_expected_critical_terms_present'])

    def test_mismatched_audio_and_empty_failed_trial_cannot_pass(self):
        report, cases, policy = self.fixture()
        report['rows'][1].update(audio_sha256='different', transcript='', completed=False, errors=['empty'])
        result = evaluate(report, cases, policy)
        self.assertFalse(result['gates']['identical_audio_pairs'])
        self.assertFalse(result['gates']['all_turns_complete_without_errors'])
        self.assertEqual(result['scores']['streaming_semantic']['trials'], 30)

    def test_missing_pair_duplicate_commit_and_leaked_tasks_fail(self):
        report, cases, policy = self.fixture()
        report['rows'].pop()
        report['rows'][1].update(commit_count=2, pending_tasks_after_close=1)
        gates = evaluate(report, cases, policy)['gates']
        for gate in ['identical_audio_pairs', 'minimum_30_trials_per_configuration', 'exactly_one_commit_per_trial', 'no_pending_tasks']:
            self.assertFalse(gates[gate])

    def test_duplicate_trial_cannot_hide_in_pair_map(self):
        report, cases, policy = self.fixture()
        report['rows'].append(dict(report['rows'][0]))
        self.assertFalse(evaluate(report, cases, policy)['gates']['identical_audio_pairs'])
