"""Guard against hiding critical recognition errors in baseline scoring."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'scripts/score_voice_baseline.py').exists())
spec = importlib.util.spec_from_file_location('score_voice_baseline', ROOT / 'scripts/score_voice_baseline.py')
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)
POLICY = json.loads((ROOT / 'benchmarks/voice/normalization.json').read_text())


class AccuracyScoringTests(unittest.TestCase):
    def test_date_and_dose_formatting_equivalents(self):
        rules = POLICY['replacements']
        self.assertEqual(scorer.normalize('the fifth of March, nineteen eighty-five', rules),
                         scorer.normalize('March 5, 1985', rules))
        self.assertEqual(scorer.normalize('ninety milligrams', rules),
                         scorer.normalize('90mg', rules))

    def test_wrong_dose_and_drug_are_not_corrected(self):
        case = {'id': 'dose', 'reference': 'Brilinta 90 milligrams', 'critical_terms': ['Brilinta', '90']}
        report = {'rows': [{'scenario': 'dose', 'repetition': 0,
                           'transcript': 'aspirin 95 mg', 'completed': True, 'errors': []}]}
        result = scorer.score(report, {'scenarios': [case]}, POLICY)
        self.assertEqual(result['rows'][0]['missing_critical_terms'], ['Brilinta', '90'])
        self.assertGreater(result['corpus_wer'], 0)

    def test_empty_transcription_remains_in_denominator(self):
        case = {'id': 'empty', 'reference': 'Please confirm tomorrow', 'critical_terms': ['tomorrow']}
        report = {'rows': [{'scenario': 'empty', 'repetition': 0,
                           'transcript': '', 'completed': False, 'errors': ['empty_transcript']}]}
        result = scorer.score(report, {'scenarios': [case]}, POLICY)
        self.assertEqual(result['corpus_wer'], 1)
        self.assertEqual(result['reference_words'], 3)
        self.assertEqual(result['critical_term_presence_rate'], 0)
        self.assertEqual(result['response_completed_trials'], 0)

    def test_ambiguous_numeric_date_requires_review(self):
        case = {'id': 'date', 'reference': 'the fifth of March 1985', 'critical_terms': ['March', '1985']}
        report = {'rows': [{'scenario': 'date', 'repetition': 0,
                           'transcript': '03/05/1985', 'completed': True, 'errors': []}]}
        result = scorer.score(report, {'scenarios': [case]}, POLICY)
        self.assertEqual(result['trials_requiring_format_review'], 1)
        self.assertIn('March', result['rows'][0]['missing_critical_terms'])
