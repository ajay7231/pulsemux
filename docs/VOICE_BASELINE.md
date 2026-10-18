# Phase 1 — Voice Call Baseline

Historical Phase 1 baseline: local and authorized synthetic measurements captured
before streaming/semantic changes. Phase 5 now adds retained matched fixtures,
digital-noise trials and human microphone/browser-playback observations in
[the release record](VOICE_RELEASE_VALIDATION.md). Reviewed retained human/noise
recordings and carrier playback remain unmeasured.

## Scope and artifacts

- Scenario manifest: [`benchmarks/voice/scenarios.json`](../benchmarks/voice/scenarios.json).
- Current detector replay: [`turn-baseline.json`](../benchmarks/voice/phase1/turn-baseline.json).
- Local Kokoro measurements: [`local-tts-baseline.json`](../benchmarks/voice/phase1/local-tts-baseline.json).
- Authorized provider timings/transcripts: [`live-synthetic.json`](../benchmarks/voice/phase1/live-synthetic.json).
- Transcript scoring: [`accuracy-baseline.json`](../benchmarks/voice/phase1/accuracy-baseline.json).
- Versioned normalization: [`normalization.json`](../benchmarks/voice/normalization.json).
- Local scorer: [`scripts/score_voice_baseline.py`](../scripts/score_voice_baseline.py).
- Browser detector runner: [`scripts/voice_turn_baseline.cjs`](../scripts/voice_turn_baseline.cjs).
- Timing runner: [`scripts/voice_latency_baseline.py`](../scripts/voice_latency_baseline.py).

The fixtures contain invented test utterances and RMS envelopes, not patient
recordings. No external provider requests were made for the recorded local runs.
The separate live run used only generated speech and a fixed acknowledgement
prompt. None of these results establishes clinical correctness or end-to-end call latency.

## Baseline call lifecycle (before Phase 2)

### Browser simulator

1. `worker-py/web/call.js` obtains a microphone with echo cancellation, optional
   browser noise suppression, and automatic gain control. Audio passes through
   telephone-band filters and `mic-worklet.js`, producing 20ms/8kHz frames.
2. The browser's energy `TurnDetector` calibrates for 25 frames (500ms), then
   requires six above-threshold frames (120ms) to start a turn. It sends mu-law
   media and speech boundary events to `/ws/voice`.
3. The configured end pause defaults to 800ms (40 frames). A 20-second duration
   limit forces a boundary. There is no transcript-aware completeness decision.
4. Python `CallAudio` maintains up to 300ms pre-roll and a bounded utterance.
   `speech_start` cancels the old turn; `speech_end` launches `transcribe_turn`.
5. `VoiceSession.transcribe_audio` sends the completed WAV to Deepgram's HTTP
   listen endpoint or Groq Whisper. There are no interim transcripts in this path.
6. `ManagedVoiceSession.handle_user_speech` retrieves approved knowledge and
   assembles the prompt before calling the base response handler.
7. The base handler emits the patient transcript, evaluates hangup/red-flag rules,
   and streams LLM content. A clause splitter calls TTS for each completed clause.
8. Kokoro generates a complete clause WAV under a shared lock. Deepgram TTS also
   returns a complete HTTP audio response. The browser receives base64 audio,
   decodes it, queues it, and starts an audio source. Browser speech can be a
   fallback and must be reported separately from the selected TTS provider.
9. New speech stops local playback and cancels the previous server turn. Mute
   disables the microphone track and suppresses frame transmission. Hangup stops
   tracks, closes the audio context/socket, and cancels server async work.

### Twilio telephone transport

1. Signed callbacks and a call-scoped stream token establish `/ws/telephony/{id}`.
2. `worker-py/app/platform/telephony.py` decodes 160-byte mu-law frames and runs
   a separate server-side energy gate with a six-frame attack and the agent's
   configured silence threshold. It does not use the browser detector's 500ms
   calibration stage.
3. On speech start, the transport cancels the old turn and clears queued audio.
   At the end boundary it calls the same `transcribe_turn` and managed runtime.
4. `PhoneTransport` converts clause WAVs to mu-law, queues them, and sends 20ms
   media frames. Playback marks support farewell completion; they do not currently
   establish per-word timing or acknowledge the first audible sample.
5. Disconnect cleanup cancels the turn and playback task and closes the call
   record. Cancelling an asyncio wrapper does not stop an already-running Kokoro
   synthesis thread; the global lock serializes subsequent synthesis work.

Go and the older `app/server.py` pipeline are outside these active call paths.
The two energy detectors should be validated independently until shared behavior
is introduced in later phases.

## Baseline timing definitions and telemetry limitations

Use monotonic clocks (`time.perf_counter` on the server, `performance.now` in the
browser). Never subtract timestamps taken on different processes or devices.
Correlate observations by call and turn ID; preserve failed, cancelled, and empty
turns rather than silently discarding them from reports.

| Measurement | Required boundary | Available today |
| --- | --- | --- |
| End-of-turn wait | Last voiced frame → committed turn boundary | Offline browser replay at 20ms resolution; no acoustic recognition claim |
| STT request latency | Completed WAV submission → recognized transcript | `telemetry_stt`; includes request/network/provider work, excludes capture and silence waiting |
| Retrieval latency | Retrieval start → selected references available | Separate RAG measurements; excluded from current voice TTFT |
| First response text | Turn commit → first visible LLM content | Not measured across the full path; current TTFT begins inside the base handler after ASR and retrieval |
| First playable server audio | Turn commit → first valid clause WAV emitted | Not a dedicated production event; the baseline observer can record WAV availability for direct synthetic trials |
| Caller-perceived response | Last voiced frame → first audio source playback / carrier audio | Not measured; server WAV receipt is insufficient |
| Full generation duration | Response handler entry → `turn_complete` | Existing `total_turn_ms`; excludes ASR/retrieval and does not wait for playback drain |
| Per-clause TTS | Synthesis call → clause WAV returned | Existing `tts_ms` measures each clause; HUD may display the latest clause rather than the first |

Other caveats:

- Existing voice timers use wall time (`time.time`); the standalone measurement
  harness uses `perf_counter` without changing runtime behavior.
- STT telemetry currently has no turn ID, so it is unsuitable for reliable
  cross-turn aggregation without additional correlation.
- TTFT includes prompt-side work inside the base handler and is not pure provider
  inference latency.
- Do not add HUD numbers to manufacture an end-to-end result: their boundaries
  differ, some stages are missing, and generation/playback can overlap.
- Synthetic direct `VoiceSession` provider trials exclude managed knowledge
  retrieval, VAD, microphone processing, and actual browser/Twilio playback.

## Captured local results

### Current browser detector, 800ms configured end pause

The runner executes the actual `TurnDetector` class from `call.js`. Frame time is
virtual: results are segmentation delays, not measured network/CPU timings.

| Scenario | Current observation | Assessment |
| --- | --- | --- |
| Complete thought | One turn, 800ms end wait | Misses the proposed ≤400ms complete-thought target |
| Medication names envelope | One turn, 800ms end wait | Segmentation only; medication recognition unmeasured |
| Numbers and units envelope | One turn, 800ms end wait | Segmentation only; number recognition unmeasured |
| Date-of-birth utterance with 1,000ms pause | Two turns | Premature commit during unfinished thought |
| Unfinished symptom utterance with 1,000ms pause | Two turns | Premature commit during unfinished thought |
| Ordinary 400ms mid-sentence pause | One turn | Preserves the turn |
| Steady room-energy envelope | No turn | Rejected in this synthetic case |
| 60ms click envelope | No turn | Rejected in this synthetic case |
| 180ms non-speech energy burst | One turn | False speech trigger; not a real recorded cough test |
| Speech above steady room-energy envelope | One turn | Segmentation succeeds for this envelope |
| Sustained 21-second speech envelope | Two turns | Existing capture limit enforced |

Eight of eleven scenarios match their specified segmentation target. This is not
an ASR accuracy rate, clinical accuracy score, or representative noise benchmark.

### Local Kokoro, Bella voice, isolated Docker process

Fixed phrase: “This is a synthetic voice quality test.” No parallel calls.
One first invocation followed by five warm samples; complete WAV generation,
including validation, is measured with `perf_counter`.

- First invocation: **1,467.12ms**.
- Warm median: **611.46ms**.
- Warm nearest-rank P95: **669.82ms**, across **five** samples.

These are small-sample local clause-generation observations. First invocation
includes model initialization; disk caches may already be warm. No provider,
recognition, microphone, retrieval, queue contention, or playback latency is
included. The image was `pulsemux-platform:phase1-baseline`; the result stores
Python version and the measured VoiceSession source hash.

## Authorized live synthetic results

Run: 2026-10-18, eight unique synthetic utterances, each submitted four times
(**32 trials**, sequential concurrency **1**). Deepgram Nova-3 HTTP recognition,
the test agent's current Groq model **qwen/qwen3.8-27b**, and local Kokoro Bella.
All 32 trials completed with no recorded provider-error events or unavailable
audio. This is a baseline observation, not a reliability guarantee.

| Measurement from completed-WAV submission | P50 | P95 | Samples |
| --- | --- | --- | --- |
| Transcription returned | 1,785.24ms | 2,413.33ms | 32 |
| First response content received | 1,948.16ms | 2,632.40ms | 32 |
| First valid response WAV received | 2,703.85ms | 3,534.47ms | 32 |

These are cumulative timings from one common origin; do not add the rows.
VAD waiting, knowledge retrieval, microphone/network ingress, browser decode,
carrier delivery and actual audible playback are excluded. The response prompt
requested a generic acknowledgement, not clinical advice or tool execution.
First fixture synthesis warms Kokoro before timed response trials.

### Transcript review

Versioned policy `synthetic-en-v1` normalizes punctuation/case and explicitly
listed number/unit/date-word formatting equivalents. It never repairs drug names
or a wrong numeric value. Numeric dates with uncertain locale are flagged rather
than silently accepted. The raw report and normalization policy are hashed in the
scored artifact.

- Normalized reference tokens: **280** across all repeated trials.
- Word-edit count: **24**, giving **8.57% normalized WER under this policy**.
  This includes unresolved date-format differences and is not a reviewed clinical
  error rate.
- Expected critical terms found: **56/72 (77.78%)**. Eight trials have missing
  literal/canonical terms; four of these need date-format review. Term presence
  alone does not establish meaning or detect every conflicting extra statement.
- All three medication names (`ticagrelor`, `Brilinta`, `metoprolol`) were preserved
  in all four repetitions of their scenario.
- The number scenario was recognized as “The reading is 150 fiveninety five”
  instead of “The reading is 155 over 95” in all four repetitions. The expected
  155/95 values were not preserved in the text. The 90mg dose was preserved after
  unit/word normalization.
- The date scenario produced `03/05/1985` instead of the spoken fifth of March,
  1985. The year was preserved; month/day equivalence needs an explicit locale
  policy and review. Do not count these as proven wrong dates or silently pass
  them as correct.
- The other six unique scenarios had zero normalized word edits in this run.
  Repetition of the same eight synthetic WAVs does not test accent diversity,
  microphone processing, real room noise, or independent speakers.

The synthetic input WAVs were not retained by this first runner. Therefore the
number failure is a demonstrated synthetic generation/recognition pipeline
problem, but cannot be attributed solely to ASR without listening to retained
input audio. Future comparison runs should retain approved synthetic WAVs and
record their hashes to guarantee identical audio across versions. The names of
noise/pause scenarios here identify their reference utterances; the live runner
does not inject the RMS replay's noise or pauses into generated speech.

### Credential provenance and scope

After the user authorized continuation of the named Deepgram/Groq trials, an
operator wrapper read only the test agent's provider configuration/connections
in a PostgreSQL read-only transaction. It resolved credentials in memory into the
benchmark process environment. No keys were printed, persisted in reports, or
passed on command lines. The standalone runner itself reads environment keys;
it receives no workspace document, prompt configuration, patient recording,
conversation history or knowledge retrieval results.

## Acceptance criteria for later phases

These are future release gates, not assertions that the current system passes.

1. Every finalized utterance produces at most one patient transcript and response
   turn; no empty or duplicate commits in the scenario corpus.
2. Complete-thought envelope commits within the initial 250–400ms target;
   annotated unfinished thoughts tolerate pauses up to 1,200ms. Tune against real
   recorded speech before treating these as production thresholds.
3. Report corpus word error rate with a versioned normalization policy, plus
   separate exact correctness of medication names, number values, units, dates,
   and negations. Digit/word equivalents require normalization review; missing or
   altered critical facts must remain visible. No aggregate accuracy regression
   against the same recorded baseline, and no critical-fact errors in the release
   acceptance corpus.
4. No cross-call audio or transcript contamination. No media while muted. No
   stale-turn playback after cancellation. Hangup/disconnect releases transport
   resources; any still-running synthesis work is explicitly accounted for.
5. Recognition failure/disconnect exits indefinite thinking and produces an
   observable outcome. Recovery never silently duplicates a completed turn.
6. Compare P50/P95 first-text and first-audio on identical audio, model settings,
   hardware, warm-up policy and concurrency. Target at least 30 successful turns
   per configuration for the initial comparison, with failures/cancellations and
   sample sizes reported separately. Do not claim the original sub-500ms SLA from
   local fixtures or five TTS samples.
7. Run manual transport cases from the manifest on both the browser and isolated
   telephone transport. Use protocol emulation before a live telephone test.
   Clinical answer/escalation correctness needs a separate reviewed corpus; the
   generic acknowledgement latency test does not evaluate it.

## Reproduce

From the repository root, with Node available:

```sh
node scripts/voice_turn_baseline.cjs > benchmarks/voice/phase1/turn-baseline.json
```

Build the utility image from an existing application image. The local run used
`pulsemux-platform:hero-restored` as its base; another checkout can first build
`pulsemux-platform:latest` with `deploy/platform.Dockerfile` and use the default
`BASE_IMAGE` instead.

```sh
docker build -f deploy/voice-baseline.Dockerfile \
  --build-arg BASE_IMAGE=pulsemux-platform:hero-restored \
  -t pulsemux-platform:phase1-baseline .
```

Local TTS using the utility image, mounted local Kokoro models, no network
and no environment credentials:

```sh
docker run --rm --network none -e PLATFORM_ENV=development \
  -v "$PWD/worker-py/models:/app/models:ro" \
  -v "$PWD/benchmarks/voice/phase1:/results" \
  pulsemux-platform:phase1-baseline \
  python -B /app/benchmarks/voice_latency_baseline.py \
  --repetitions 5 --output /results/local-tts-baseline.json
```

For an explicitly authorized live synthetic trial, supply `DEEPGRAM_API_KEY` and
`GROQ_API_KEY` in the shell environment. The baseline Docker image uses Python
3.12 and the installed application requirements:

```sh
docker run --rm -e PLATFORM_ENV=development -e DEEPGRAM_API_KEY -e GROQ_API_KEY \
  -v "$PWD/worker-py/models:/app/models:ro" \
  -v "$PWD/benchmarks/voice/phase1:/results" \
  pulsemux-platform:phase1-baseline \
  python -B /app/benchmarks/voice_latency_baseline.py --live \
  --repetitions 4 --output /results/live-synthetic.json
```

Live mode generates audio locally from the manifest references, sends that audio
to Deepgram, and sends recognized synthetic text plus a fixed evaluation prompt
to Groq. It uses paid provider APIs. It does not read workspace connections,
hospital knowledge, or recorded patient audio. Never check in keys or substitute
patient recordings into this fixture directory. Transcription output should be
reviewed before saving or committing a live report.

Score a saved run without external requests:

```sh
python3 -B scripts/score_voice_baseline.py \
  benchmarks/voice/phase1/live-synthetic.json \
  --output benchmarks/voice/phase1/accuracy-baseline.json
```

The scorer refuses a scenario manifest whose hash differs from the measured run.
Tests cover date/dose formatting equivalence, wrong drug/dose preservation as
errors, empty-transcript inclusion, and ambiguous numeric-date review.

## Validation of baseline tooling and existing lifecycle checks

- Four transcript-scoring tests pass (format equivalents, incorrect drug/dose,
  empty recognition, and ambiguous numeric dates).
- Seven existing Python telephony tests pass with provider interactions mocked.
  They cover signed routing, consent enforcement, uncertain outbound outcomes,
  campaign dispatch behavior, codec polarity, and farewell playback marks.
- Eleven existing browser-controller/audio tests pass, including stale-turn audio
  rejection and playback-draining hangup. These use browser mocks, not hardware.
- The rebuilt `pulsemux-platform:phase1-baseline` image reproduces transcript
  scoring with `--network none` and no credentials or database mount.
- Application readiness remains healthy. No application call-path code was changed,
  and no telephone calls were placed by the baseline or tests.

These checks do not substitute for the microphone/carrier cases below.

## Phase 1 gaps revisited in Phase 5

- Retained, reviewed speech/noise recordings with audio hashes, broader speaker
  coverage, and a locale policy for date normalization.
- Browser playback API timestamps are now captured for both HTTP and streaming
  paths, with three speech turns per configuration; real carrier timing remains open.
- The user reported passing microphone, pause, interruption and mute checks;
  retained, annotated human speech/noise recordings remain open.

Provider timings and normalized transcript scores are now captured for the
synthetic direct-runtime configuration. Phase 5 adds small-sample local playback
observations; acoustic output, carrier delivery and general real-world recognition
accuracy still cannot be inferred from these results.
