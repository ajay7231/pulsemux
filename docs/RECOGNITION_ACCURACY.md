# Recognition accuracy follow-up

This follow-up reuses the Phase 5 synthetic references, retained audio and
`synthetic-en-v1` normalization. It does not change expected words, normalize
incorrect medications into correct ones, or infer a locale from numeric dates.

## Runtime changes

- Both Deepgram transports share Nova-3, English, `punctuate=true` and
  `smart_format=false`. Spoken dates remain words rather than becoming an
  ambiguous `03/05/1985`. Numeric caller input is not silently reinterpreted;
  clinical identity/date verification still requires caller confirmation.
- **Voice & models → Clinical vocabulary** accepts up to 25 plain terms, five
  words / 80 characters each. The API validates and deduplicates the list.
  Existing agents default to an empty list. Drafts and published call snapshots
  carry their own vocabulary into both browser and telephone transports.
- The supplied post-PCI protocol's complete medication table provides the
  [explicit test vocabulary](../benchmarks/voice/post-pci-vocabulary.json),
  including drugs absent from the recognition references. No vocabulary is
  extracted from an expected transcript. It has also been saved to the existing
  Post-PCI Knowledge Test Agent draft through the dashboard; it is not published.
- Finalized streaming words below 0.8 confidence trigger **at most one** full-turn
  HTTP transcription using the same Deepgram connection credentials and terms.
  Confident turns do not make this additional request. A failed verification
  emits a repeat-needed warning instead of sending the uncertain text to the LLM.
  Verification has a four-second outer timeout and is cancelled on interruption.
  There is no automatic switch to another recognition provider.
- Audio is retained only in a call-owned 30-second ring (240KB at 8kHz mu-law)
  plus the bounded turn snapshot while the turn is processed. It is cleared on close,
  never persisted, and never included in browser events, history or logs.
  Confidence is not a guarantee of correctness: confident recognition errors
  still require broader evaluation and clinical confirmation workflows.

Deepgram documents [independent punctuation/smart formatting](https://developers.deepgram.com/docs/smart-format)
and [Nova-3 vocabulary prompting](https://developers.deepgram.com/docs/keyterm).
A targeted medical-model probe recovered a medication name but damaged a BP
phrase, so the runtime remains on general Nova-3.

## Evidence and limits

The [policy-only run](../benchmarks/voice/accuracy-fix/policy-only-provider.json)
and [unchanged score](../benchmarks/voice/accuracy-fix/policy-only-score.json)
are retained, including their failed WER gate. Punctuation/vocabulary alone
resolved critical terms and date review, but WER was 1.43% HTTP versus 3.57%
streaming. Provider metadata on the retained synthetic inputs showed low word
confidence for the remaining “cast”/“test” and opening-word failures; this
motivated the generic confidence review rather than word substitutions.

The full comparison uses 32 trials per path, four repetitions of eight references,
with clean speech and deterministic 20dB digital noise. These are in-sample
improvements, not an independent held-out accuracy estimate. Real human/noise
recordings and actual carrier playback remain separate acceptance work.

## Final matched results

[Raw 64-trial report](../benchmarks/voice/accuracy-fix/paired-provider.json) ·
[Scored gates](../benchmarks/voice/accuracy-fix/paired-score.json)

All eight existing automated gates pass. All 16 fixture hashes match the original
Phase 5 report; the scenario manifest and normalization policy are unchanged.

| Measure | HTTP fixed pause | Semantic streaming + selective review |
| --- | --- | --- |
| Normalized WER | 1.43% | 1.43% |
| Expected critical-term presence | 100% | 100% |
| Ambiguous numeric-date flags | 0 | 0 |
| Completed trials / duplicate commits / errors / task leftovers | 32 / 0 / 0 / 0 | 32 / 0 / 0 / 0 |
| Speech end → first response text P50 / P95 | 2,731 / 3,472ms | 1,254 / 3,105ms |
| Speech end → first valid WAV P50 / P95 | 3,422 / 4,204ms | 2,237 / 3,914ms |
| Commit → first valid WAV P50 / P95 | 2,619 / 3,398ms | 1,566 / 3,197ms |

There were 14 selective HTTP reviews in 32 streaming trials. Accuracy is improved
from the historical 8.57% streaming WER and 86.11% expected-term presence. This is
not zero WER: noisy recordings still lose opening words in both paths.

Verification adds provider requests and latency. The policy-only streaming run
had a 1,734ms median and 2,257ms P95 speech-to-WAV boundary; the final run's median
and tail are slower, while remaining below its concurrent HTTP baseline. These
are small descriptive samples, not an isolated causal estimate or a sub-500ms SLA.
The confidence threshold was informed by this corpus; a held-out human corpus is
still required before claiming generalization.

Both new paths use the saved agent's current `openai/gpt-oss-120b` Groq model,
local Kokoro Bella and the same generic acknowledgement prompt. The historical
run used a different response model, so historical end-to-end timings should not
be treated as a controlled latency comparison. No patient inputs, managed RAG or
real carrier calls were included. First WAV on the server excludes browser,
acoustic and carrier playback.

Validation: 66 targeted Python tests passed in network-disabled Docker; 17
dashboard tests, lint, type checking, production build and bundle budget passed.
The API was rebuilt as `pulsemux-platform:accuracy-fix`, restarted on port 8001,
and `/readyz` returned `{"status":"ready"}`. The accuracy-fix image remains
available locally; obsolete stopped API containers were subsequently removed
without deleting images or persistent data.

## Reproduce with the existing runner

Use retained fixtures (their SHA-256 hashes are in the report), process-environment
provider keys, and the explicit `--live` switch. Never put credentials on command
lines or in reports. Build the normal application image, then build
`deploy/voice-validation.Dockerfile` using that image as `BASE_IMAGE`.

```sh
python scripts/voice_release_validation.py --live --model openai/gpt-oss-120b \
  --repetitions 4 --fixtures /data/phase5-fixtures \
  --vocabulary benchmarks/voice/post-pci-vocabulary.json --output /reports/paired.json
python scripts/score_voice_release.py /reports/paired.json --output /reports/score.json
```

For the separate supplementary check, use `--repetitions 2` and
`--scenarios benchmarks/voice/critical-negations.json`. Four trials per path do
not meet the main comparison's 30-trial sample gate; report those accuracy
observations separately.

The [eight supplementary dose/negation trials](../benchmarks/voice/accuracy-fix/paired-negations.json)
and [their score](../benchmarks/voice/accuracy-fix/negation-score.json) also reused
all four original fixture hashes. Both paths had 2.94% WER, preserved all expected
negations/doses/units, and completed without duplicate commits, errors or pending
tasks. Their minimum-30-trials gate remains false by design (four per path).
