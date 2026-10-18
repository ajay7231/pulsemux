#!/usr/bin/env python3
"""Score saved synthetic transcripts locally; never contacts providers."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def normalize(value, rules):
    value = unicodedata.normalize('NFKC', value).lower()
    value = re.sub(r'(?<=\d)(?=mg\b)', ' ', value)
    value = re.sub(r'[^\w\s]', ' ', value)
    value = ' '.join(value.split())
    for source, target in rules:
        value = re.sub(r'(?<!\w)' + re.escape(source) + r'(?!\w)', target, value)
    return value.split()


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (word != other)))
        previous = current
    return previous[-1]


def contains(tokens, term):
    return any(tokens[i:i + len(term)] == term for i in range(len(tokens) - len(term) + 1))


def score(report, scenarios, normalization):
    references = {s['id']: s for s in scenarios['scenarios']}
    rows, edits, words, critical_pass, critical_total = [], 0, 0, 0, 0
    errors = Counter()
    for result in report['rows']:
        case = references[result['scenario']]
        rules = normalization['replacements']
        ref = normalize(case['reference'], rules)
        hyp = normalize(result.get('transcript') or '', rules)
        missing = [term for term in case['critical_terms'] if not contains(hyp, normalize(term, rules))]
        review = []
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', result.get('transcript') or ''):
            review.append('numeric_date_requires_locale_review')
        n = distance(ref, hyp)
        edits += n
        words += len(ref)
        critical_total += len(case['critical_terms'])
        critical_pass += len(case['critical_terms']) - len(missing)
        errors.update(result.get('errors', []))
        rows.append({'scenario': case['id'], 'repetition': result['repetition'],
                     'reference_words': len(ref), 'word_edits': n,
                     'wer': round(n / len(ref), 4) if ref else None,
                     'missing_critical_terms': missing,
                     'all_critical_terms_present': not missing, 'manual_review': review,
                     'response_completed': bool(result.get('completed')),
                     'errors': result.get('errors', [])})
    return {'normalization_version': normalization['version'], 'trials': len(rows),
            'reference_words': words, 'word_edits': edits,
            'corpus_wer': round(edits / words, 4) if words else None,
            'critical_terms_present': critical_pass, 'critical_terms_total': critical_total,
            'critical_term_presence_rate': round(critical_pass / critical_total, 4) if critical_total else None,
            'trials_with_missing_critical_terms': sum(not r['all_critical_terms_present'] for r in rows),
            'trials_requiring_format_review': sum(bool(r['manual_review']) for r in rows),
            'response_completed_trials': sum(r['response_completed'] for r in rows),
            'error_events': dict(errors), 'rows': rows,
            'limitations': ['Checks expected term presence, not clinical correctness or absence of conflicting extra facts.',
                           'Locale-ambiguous numeric dates are flagged for review and are not silently treated as equivalent.',
                           'Repeated synthetic voice samples do not establish generalization to patients, microphones or accents.',
                           'WER denominator includes failed/empty transcription trials; empty transcripts are not dropped.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--scenarios', type=Path, default=ROOT / 'benchmarks/voice/scenarios.json')
    parser.add_argument('--normalization', type=Path, default=ROOT / 'benchmarks/voice/normalization.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.report.read_bytes()
    cases = args.scenarios.read_bytes()
    report = json.loads(source)
    if report.get('mode') != 'live_synthetic':
        parser.error('Expected a live_synthetic transcript report')
    if hashlib.sha256(cases).hexdigest() != report.get('scenario_sha256'):
        parser.error('Scenario manifest differs from the measured run')
    normalization = args.normalization.read_bytes()
    result = score(report, json.loads(cases), json.loads(normalization))
    result.update({'report_sha256': hashlib.sha256(source).hexdigest(),
                   'normalization_sha256': hashlib.sha256(normalization).hexdigest()})
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'limitations'}}, indent=2))


if __name__ == '__main__':
    main()
