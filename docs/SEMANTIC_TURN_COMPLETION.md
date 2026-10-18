# Phase 3 — Local semantic turn completion

## Behavior

Deepgram browser tests and Twilio calls share `SemanticTurnCompletion` in the
Python runtime. Both transports submit a VAD pause candidate at approximately
350ms (360ms on 20ms audio frames). A candidate requests recognition finalization
without consuming the audio window or sending text to the language model.

Finalized text or an endpoint signal, combined with a complete local phrase,
permits commitment after the short pause. Dangling conjunctions, auxiliaries,
unfinished introductions, trailing numbers, provisional-only recognition and
unknown/unpunctuated phrases wait up to 1,200ms. Provider endpoint events never
commit by themselves while VAD still indicates speech. No extra model request is
made. These are conservative English rules, not a clinical meaning classifier.

Speech resuming before commitment cancels its timer and preserves the accumulated
recognition window under the new transport turn ID. Resuming after commitment
uses the existing response cancellation and playback interruption path. Final
segments and newer interim suffixes are combined by timestamp so an old final
cannot erase an unfinished suffix. Only finalized words enter patient history.

Mute explicitly flushes the pre-mute window with zero trailing silence. A hard
20-second limit spans continued fragments; later speech starts another bounded
window. Empty finalized turns produce the existing retry message without a model
request or disconnect. Stale/duplicate candidates do not submit another turn.
Hangup closes timers, recognition collectors and the provider connection.

## Configuration and rollback

The defaults, also forwarded by `deploy/platform-compose.yml`, are:

```dotenv
SEMANTIC_TURN_ENABLED=1
SEMANTIC_TURN_COMPLETE_MS=350
SEMANTIC_TURN_INCOMPLETE_MS=1200
```

The short pause accepts 250–400ms. The longer pause must exceed it and be at most
1,800ms. Set `SEMANTIC_TURN_ENABLED=0` and restart to retain persistent recognition
with the agent's saved fixed pause. Groq Whisper and the explicit Deepgram HTTP
rollback keep the saved pause policy because they lack streaming transcript cues.
Deepgram endpointing uses the short pause when semantic completion is enabled.

Refresh the dashboard and start a new call after deployment. Listening remains
active during a reversible pause; thinking starts at the server's `turn_committed`
event. Phase 4 now adds [interim previews and precise pipeline states](SIMULATOR_FEEDBACK.md),
including a transcribing state between commitment and final recognition.

The local API was rebuilt as `pulsemux-platform:phase3-semantic` and restarted
with semantic completion enabled at 350/1,200ms. Its readiness endpoint returned
`{"status":"ready"}` and the deployed module/configuration were verified.

## Verification

- 51 targeted Python tests passed, including virtual-time timing, continued
  fragments, stale results, empty recognition, hard limits, cleanup, actual
  browser WebSocket and signed Twilio route integration with emulated providers.
- 14 browser-controller tests and two dashboard agent-test checks passed.
- Dashboard type checking, production build and bundle budget passed.
- Two real Deepgram synthetic calls passed. See
  [semantic-smoke.json](../benchmarks/voice/phase3/semantic-smoke.json) and the
  repeatable `scripts/semantic_turn_smoke.py` (requires an explicitly supplied
  Deepgram API key and semantic streaming enabled).

The complete-sentence synthetic call committed 523.3ms after its scripted speech
boundary. The continued sentence committed 641.5ms after its last boundary,
with no commit during its 1,000ms unfinished pause. Both returned one response
and left zero tasks on close. The second transcript omitted the initial “I”; no
recognition-accuracy improvement is claimed.

These are two individual observations, not latency percentiles or a comparison
against the HTTP baseline. The 350ms value is a pause floor; final recognition
arrival can delay commitment. These checks used scripted VAD boundaries and
generated speech, with no microphone recording, LLM, retrieval or real telephone
call. Wider recorded-noise, concurrent-call and end-to-end comparisons remain
Phase 5; the prior clinical-number recognition limitation remains unresolved.
