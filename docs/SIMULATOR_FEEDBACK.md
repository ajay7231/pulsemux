# Phase 4 — Shared runtime and simulator feedback

## Changes

Browser and Twilio sessions continue to use the same Python recognition adapter
and semantic completion controller. The dashboard and standalone simulator reuse
the same JavaScript call controller. No parallel recognition or completion engine
was added for the simulator.

The live transcript now has a separate **Hearing you / Not final** preview.
It combines finalized recognition segments with the current interim suffix for
the uncommitted caller turn. Preview updates replace text rather than creating
conversation messages. They are not persisted, passed to the language model, or
used as clinical history. Only the committed final transcript enters history.
The preview clears on final transcription, errors, empty results, mute, a new
turn, typed input, hangup and teardown. Late updates for another turn or socket
are ignored. Text is rendered with `textContent`, never as HTML.

The preview is outside the conversation's live log to avoid announcing every
recognition revision to screen readers. Its label makes provisional status
explicit, and the preview remains hidden until there is text to display.

## Call states

| State | Trigger |
| --- | --- |
| Checking microphone | Waiting for microphone permission/setup |
| Connecting to agent | Socket established; call server has not acknowledged start |
| Listening | Call acknowledged and no pending recognition, response or playback |
| Listening to you | Voice activity detected; a semantic pause remains reversible |
| Transcribing | Turn committed, waiting for the final transcript |
| Assistant is thinking | Final caller transcript submitted to the agent |
| Assistant speaking | Audio playback is active |
| Microphone muted | Capture track disabled; worklet media transmission blocked |
| Disconnected | Recognition or network failure ended the session |
| Reconnecting | User requested a fresh call; waiting for its connection/acknowledgement |

Calibration and goodbye playback keep their existing explicit states. The UI
does not show connected or send microphone media before the server acknowledges
the call. Muting also clears the room reading instead of showing stale levels.

Reconnect is explicit and starts a **new** call record. There is no automatic
audio replay, provider fallback or claim that the previous conversation resumed.
Authentication failures continue to direct the user to sign in.

## Verification and deployment

- 51 targeted Python checks passed for recognition, semantic completion, call
  control, TTS and telephone transport. Browser integration explicitly checks
  that provisional recognition does not enter persisted call events.
- 14 JavaScript controller checks and six dashboard tests passed. These cover
  acknowledgement gating, preview replacement/clearing, recognition versus
  thinking, real worklet-callback suppression while muted, explicit reconnect,
  stale socket messages, queued goodbye playback and resource cleanup.
- Dashboard lint, type checking, production build and bundle budget passed.
- Rebuilt and restarted the API as `pulsemux-platform:phase4-feedback`;
  `/readyz` returned `{"status":"ready"}`. Verified the refreshed agent editor
  and integrated test screen in Chrome, without starting the microphone.

The behavioral browser tests use simulated microphone/socket inputs and the
transport tests emulate provider responses. No new live microphone or carrier
call was made in this phase. Phase 3's synthetic provider evidence remains
separate; broader real-audio, concurrent-call, accuracy and latency validation
belongs to Phase 5. Clinical-number recognition limitations remain unresolved.

Refresh the dashboard before starting a new call so the current assets are loaded.
