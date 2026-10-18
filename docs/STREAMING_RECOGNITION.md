# Phase 2 — Persistent Deepgram Recognition

## Scope

Browser `/ws/voice` and Twilio `/ws/telephony/{call_id}` now use the same
`DeepgramCallStream` when the saved agent selects Deepgram. One provider socket
is opened before the call starts and remains owned by that call until stop,
disconnect, timeout, replacement, or recognition failure. Provider keys come from
the saved workspace connection and stay on the server.

Groq Whisper remains an explicit utterance-based choice. There is no automatic
cross-provider fallback and no synthetic/mock recognition in the live adapter.
Set `DEEPGRAM_STREAMING_ENABLED=0` and restart the application to roll Deepgram
back to its previous HTTP utterance path. The production Compose configuration
forwards this flag; local containers can receive it through their environment.

## Audio and turn ownership

- Forward raw mono 8kHz mu-law frames directly to Deepgram. Continuous audio
  includes ordinary silence while the microphone is open. A muted browser sends
  no audio; application-level keepalives preserve its provider connection.
- Provider interim results emit `transcript_interim` only. They do not enter
  conversation history, clinical actions, or the LLM. Phase 4 renders them in a
  [separate provisional preview](SIMULATOR_FEEDBACK.md).
- Phase 2 retained the fixed browser/server VAD boundary. Phase 3 now adds
  [local semantic completion](SEMANTIC_TURN_COMPLETION.md) by default; the fixed
  policy remains available through its rollback flag.
- Finalized words are indexed by provider audio timestamps. Repeated results for
  the same word interval update one entry; repeated phrases at different times
  remain separate. Each turn consumes only words within its captured audio range.
- Speech start includes the existing 300ms pre-roll. Previously consumed ranges
  are excluded. Provider results arriving late cannot move a new turn's boundary.
- At speech end, enqueue `Finalize` after the preceding audio and wait for final
  coverage through the last voiced frame. Do not assume every flush returns a
  `from_finalize` acknowledgement, and never convert interim guesses into final
  patient history. A bounded timeout ends recognition visibly rather than silently
  using incomplete text.
- Browser boundary messages now carry actual trailing silence. Mute flushes with
  zero trailing silence; the forced 20-second boundary also uses its actual
  silence count. Phone VAD supplies its own measured trailing silence.
- Cancelling a response does not cancel a provider flush already in progress.
  Collection is call-owned and serialized; teardown cancels all collectors.

This follows Deepgram's documented distinction between finalized segments and
utterance boundaries, and its Finalize/KeepAlive protocol:

- https://developers.deepgram.com/docs/understand-endpointing-interim-results
- https://developers.deepgram.com/docs/finalize
- https://developers.deepgram.com/docs/audio-keep-alive

## Bounds and failures

Audio backlog is bounded to 250 20ms frames (five seconds). Overflow fails
visibly; frames are not silently dropped. Connection establishment, socket
writes, finalization and close are bounded. Word storage has a fixed upper bound
and old history is pruned. Call instances share neither recognition buffers nor
provider connections.

A provider failure produces a sanitized error and ends the browser call with a
restart instruction. Telephone calls end through the existing Twilio call
control; no browser-voice fallback is assumed for a telephone. Startup failures
close the call record as failed. Cleanup closes the provider socket and awaits
reader, writer, keepalive and collection tasks.

## Timing

Streaming `telemetry_stt` includes the turn ID and
`measurement=turn_boundary_to_final_transcript`. It measures the remaining wait
for a final transcript after the local turn boundary; recognition has already
been running during speech. It is not equivalent to the old completed-recording
HTTP request duration and must not be presented as a directly comparable ASR
speedup. End-to-end measurements still need capture, VAD waiting, retrieval,
response generation, synthesis, and actual playback boundaries.

## Verification

`worker-py/tests/test_live_stt.py` covers provisional/final handling, repeated
results, late old-turn results, identical phrases in different turns, cancellation
during flush, missing finalization, bounded backlog, keepalive/disconnect,
resource cleanup, Groq routing/rollback, saved credentials in browser integration,
and the signed telephone path using the same adapter. Provider sockets are
emulated; these tests place no telephone calls.

`worker-py/tests/call.test.cjs` additionally verifies that muting during speech
sends a zero-silence boundary and suppresses media until unmuted.

Real provider verification is recorded separately from mocked transport tests.
No clinical-answer accuracy claim follows from this transport change.

The deployed Phase 2 image passed 36 targeted Python tests, 12 browser-controller
tests and two dashboard agent-test checks. Dashboard lint, type checking, build
and bundle budget checks passed. The local API was rebuilt as
`pulsemux-platform:phase2-streaming`, restarted with streaming enabled, and
`http://127.0.0.1:8001/readyz` returned `{"status":"ready"}`. Start a new call
after refreshing the dashboard to exercise the updated runtime.

## Real provider smoke result

See [`streaming-smoke.json`](../benchmarks/voice/phase2/streaming-smoke.json).
Three generated utterances were paced in real time through **one** Deepgram
connection at 8kHz mu-law. All three produced nonempty final transcripts, interim
events were observed, no failure event occurred, and teardown left zero adapter
tasks. Synthetic input WAVs were retained under ignored local
`worker-py/data/phase2-synthetic-audio/`; their hashes are in the report.

The remaining wait after the existing 800ms silence boundary was 474.60ms,
0.27ms, and 358.50ms for these three samples. The near-zero sample had already
finalized while speech/silence was streaming. These are individual observations,
not P50/P95 or end-to-end speedup claims, and are not comparable to the Phase 1
HTTP request timing without matching measurement boundaries and audio encoding.

The medication-name phrase was preserved in this smoke run. The blood-pressure
phrase still recognized 155 over **90** instead of 155 over **95**; streaming
transport does not establish critical-number accuracy. Review retained audio and
use the Phase 1 scoring/review process before making accuracy claims. No clinical
response or real telephone call was generated by this smoke test.
