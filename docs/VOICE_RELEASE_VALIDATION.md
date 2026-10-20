# First delivery — validation and release record

Date: 2026-10-18. **Historical Phase 5 record; overall release acceptance remains open.** The implementation and
validation tools are deployed for testing. Faster timings do not override the
failed recognition-quality gates below.

**Update:** The [recognition accuracy follow-up](RECOGNITION_ACCURACY.md) closes
these automated accuracy gates on the same fixture hashes and unchanged scorer.
The historical results below are preserved; human/noise and carrier acceptance
remain open.

## Matched provider comparison

[Raw paired run](../benchmarks/voice/phase5/paired-provider.json) ·
[Scored gates](../benchmarks/voice/phase5/paired-score.json)

Thirty-two trials per configuration used identical retained, SHA-256-hashed
8kHz mu-law synthetic audio: eight references repeated four times, alternating
clean speech and digitally added noise targeting 20dB SNR. Trial ordering
alternated between the HTTP and streaming paths. Both used the saved test
agent's `qwen/qwen3.8-27b` model, local Kokoro Bella and a fixed generic
acknowledgement prompt. No patient audio, hospital knowledge or live clinical
actions were used. Raw fixture WAVs are retained locally under ignored
`worker-py/data/phase5-fixtures/`; the report records their names and hashes.

| Boundary (server monotonic clock) | HTTP fixed pause P50 / P95 | Semantic streaming P50 / P95 |
| --- | --- | --- |
| Scripted speech end → first response content | 2,399 / 2,884ms | 798 / 1,598ms |
| Scripted speech end → first valid response WAV | 3,310 / 4,018ms | 1,618 / 2,289ms |
| Committed turn → first valid response WAV | 2,508 / 3,213ms | 957 / 1,467ms |

All 64 turns completed without recorded provider-error events, duplicate commits
or remaining adapter tasks. These are small-corpus descriptive percentiles.
Boundaries are scripted after fixture audio, not measured acoustic speech ends.
The HTTP baseline includes its 800ms silence wait; streaming recognition runs
during paced speech and uses the local completion policy. Neither timing includes
managed hospital retrieval, browser decoding/playback or carrier delivery.

Historical Phase 1 audio was not retained. This is a new matched baseline, not
an identical replay of the historical recording. The utility run has concurrency
one; host/provider load is not an isolated laboratory control.

## Accuracy and failed gates

Both configurations were scored using unchanged `synthetic-en-v1` normalization,
including failed/empty trials in the denominator. Drug names and wrong numeric
values are never repaired by normalization.

| Gate / observation | Result |
| --- | --- |
| Identical audio, ≥30 trials per configuration | Pass |
| One commit, completed response, no errors or task leftovers | Pass |
| Normalized WER without regression | **Fail: 6.43% HTTP → 8.57% streaming** |
| All expected critical terms present | **Fail: 86.11% presence in both paths** |
| Unresolved numeric-date formatting | **Fail: four trials per path need review** |

The noisy medication reference missed literal “Brilinta” in two trials per path.
The date reference became `03/05/1985`; no locale interpretation was silently
accepted. The streaming path additionally misrecognized noncritical words in
some references, including “test” as “cast.” All main-run 155/95 references
preserved those values, but that does not erase earlier numeric failures or
establish general clinical accuracy.

An additional [eight paired negation/dose trials](../benchmarks/voice/phase5/paired-negations.json)
preserved the expected negations, 90/95 values and units under the scorer:
[supplementary score](../benchmarks/voice/phase5/negation-score.json).
There are only four samples per configuration in this supplementary run; its
30-trial gate correctly remains false. Term presence does not prove absence of
contradictory facts, clinical answer correctness or generalization to patients.

## Segmentation, concurrency and failure behavior

- [Actual VAD plus Python-rule replay](../benchmarks/voice/phase5/turn-comparison.json):
  8/11 baseline targets → 10/11 semantic targets. Both scripted one-second
  unfinished pauses remain in one turn; complete-thought envelopes commit at
  360ms on 20ms frames. Transcript cues are supplied, not recognized audio.
- The 180ms non-speech energy burst still triggers VAD. This failing scenario is
  retained; the energy gate is not a neural speech/noise classifier.
- [Offline lifecycle stress](../benchmarks/voice/phase5/lifecycle-stress.json):
  80 cases, peak 20 concurrent sessions, no cross-call responses, no failed
  cases, and one harness task before/after. Cases include injected disconnect,
  hangup during a pending turn, successful completion and accelerated idle
  heartbeats. Providers are emulated and networking is disabled.
- [Live generated-silence check](../benchmarks/voice/phase5/live-idle-disconnect.json):
  one Deepgram connection survived 30 real seconds of digital silence plus
  15 seconds without audio using production keepalives. Deliberately closing the
  socket produced one failure callback and zero remaining tasks.
- Regression tests cover response cancellation, late/stale results, empty
  recognition, bounded long speech, mute suppression, farewell drain and signed
  telephone routing. No real telephone call or gateway SLA was tested.

## Human microphone observations

The user ran the supplied fictional test inputs and reported correct 155/95 and
Brilinta 90mg recognition, the one-second pause, interruption and mute behavior.
This is user-observed validation; the medication/noise result is not independently
verified against a retained recording.

The local microphone comparison (`benchmarks/voice/phase5/microphone-comparison.json`)
retains both local browser timing exports. These user telemetry files are ignored by Git:

- HTTP export (local `benchmarks/voice/phase5/microphone-http-timings.json`): three
  speech turns including goodbye, median speech → playback API start **3,754ms**.
- Streaming export (local `benchmarks/voice/phase5/microphone-streaming-timings.json`):
  three speech turns including goodbye, median **2,256ms**.

The user repeated the requested BP/repeat/goodbye sequence on the same agent.
Speech recordings and agent response lengths are not identical, so this is an
observational comparison, not a controlled percentile benchmark. No microphone
audio or room-noise recording was retained. Acoustic conditions and equipment
were not recorded. Browser playback API start is not sound measured at the ear.
No carrier timing is available.

The older baseline export's `commit_notice_*` fields represent the **local fixed
VAD boundary**. Current exports include `commit_origin` to distinguish this from
server notification receipt and typed submission. Never subtract clocks from
different processes or add the independent HUD latency values.

## Rollout and rollback

The dashboard now provides **Export timings** and separate speech → playback and
commit-reference → playback values. Exports contain bounded numeric observations,
turn IDs and provider/voice identifiers, with no audio, transcript, patient data
or secrets. Up to 1,000 turns are retained in browser memory; a fresh call resets
the export. Interrupted/error/continued turns retain missing values as null.

The temporary HTTP baseline has been captured. The final runtime is restored to
`DEEPGRAM_STREAMING_ENABLED=1`, `SEMANTIC_TURN_ENABLED=1`, 350/1,200ms local rules.
The API is built as `pulsemux-platform:phase5-validation`. This is a local test
deployment, **not a clinical production release approval**.

Final verification: 60 targeted Python checks passed in the network-disabled
validation image, plus 15 browser-controller and six dashboard checks. Dashboard
lint, type checking, build and bundle budget passed. The restarted API returned
`{"status":"ready"}`; both streaming and semantic flags were verified as `1`.

- `SEMANTIC_TURN_ENABLED=0`: persistent Deepgram with the saved fixed pause.
- `DEEPGRAM_STREAMING_ENABLED=0`: previous Deepgram HTTP utterance path.
- Groq remains an explicit choice; there is no automatic cross-provider switch.

## Reproduce

Build the application with the existing platform Dockerfile, then build the
separate benchmark image (no new application dependencies):

```sh
docker build -f deploy/voice-validation.Dockerfile \
  --build-arg BASE_IMAGE=pulsemux-platform:phase5-validation \
  -t pulsemux-platform:voice-validation .
python3 scripts/semantic_turn_replay.py --output /tmp/turn-comparison.json
python3 scripts/score_voice_release.py benchmarks/voice/phase5/paired-provider.json \
  --output /tmp/paired-score.json
```

The semantic replay requires local Node and the checked-in virtual-clock test
helper. The lifecycle runner can execute in the validation image with networking
disabled. Provider runners require an explicit `--live` switch for paired trials
and process-environment keys; never put keys on command lines or in reports.
Example runner arguments:

```sh
python scripts/voice_release_validation.py --live --model qwen/qwen3.8-27b \
  --repetitions 4 --fixtures /data/phase5-fixtures --output /reports/paired.json
python scripts/voice_runtime_stress.py --calls 80 --concurrency 20 \
  --output /reports/lifecycle.json
python scripts/streaming_idle_check.py --output /reports/idle.json
```

## Remaining acceptance work

1. **Same-fixture automated accuracy gates closed:** the follow-up recovered
   medication terms and WER non-regression without changing references or scoring.
   Generalization to reviewed human speech remains open below.
2. **Date formatting policy implemented:** retain spoken dates without automatic
   locale-dependent rewriting; confirm ambiguous caller-supplied dates explicitly.
3. Retain consented, annotated human speech/noise recordings with broader speaker
   coverage. Current microphone observations and digital-noise fixtures do not
   substitute for that corpus.
4. Measure carrier playback when a test number/recipient and authorization exist.
   Protocol-emulated telephone tests are complete; no real outbound call was made.

Items 3–4 remain explicit open gates. `plan_2.md` must not be marked fully accepted until
they are resolved or its acceptance criteria are explicitly revised by the user.
