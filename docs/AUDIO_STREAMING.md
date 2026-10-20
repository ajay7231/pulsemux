# End-to-end speech output

## Delivery plan and implementation

1. Replace live Deepgram WAV buffering with incremental HTTP response reads.
   Keep credentials and the reusable HTTP connection pool scoped to one call.
2. Separate LLM reading from speech synthesis with an ordered, four-clause queue
   and structured task cancellation. Send complete clauses early, preserve decimal
   doses across token boundaries, and drain every remaining clause at completion.
3. Send 20ms raw-audio messages over the existing authenticated WebSocket.
   Browser playback uses one continuous AudioWorklet to resample 24kHz signed
   little-endian PCM, without `decodeAudioData`, per-frame filters or whole WAVs.
   Telephone adapters receive native 8kHz mu-law frames and preserve existing
   Twilio marks / Plivo checkpoints, pacing and playback-aware hangup.
4. Bound pending work, verify interruption/failure/cleanup and early playback,
   then build the dashboard and recreate the application Docker container.

All four steps are implemented. No SDK or additional package is required.

## Flow and limits

`LLM SSE → clause queue → Deepgram HTTP audio stream → audio_chunk → playback`

The Deepgram API still receives a complete clause per request. Its response body
is consumed as it arrives. This is HTTP audio streaming, not a persistent Deepgram
TTS WebSocket/text-token stream. Connection pooling avoids opening a new client
per clause. Short complete sentences are emitted without waiting for a longer
sentence; numeric decimals are not split at a token boundary.

- Four pending clauses; a blocked speech task applies backpressure to LLM reading.
- One HTTP pool per call, closed with call cleanup. Cancellation closes the active
  response without handing old audio to the next turn. Keys remain server-side.
- 20ms audio chunks: up to 960 bytes mono PCM, or 160 bytes mu-law.
- Browser output is paced to a 500ms lead. One playback worklet owns a bounded
  three-second ring and an 80ms startup jitter buffer. A continuous resampling
  phase and one downstream lowpass filter preserve state across 20ms packets.
  Brief 3ms fades prevent hard edges at real underruns, interruption and end.
  Overflow fails visibly; queued words are never silently dropped.
- Telephone queue holds at most 50 frames (one second), with existing 20ms pacing.
- Provider connection timeout five seconds, read timeout 15 seconds, and overall
  per-clause timeout/duration limit 45 seconds. Audio is never persisted.
- Interruption cancels both LLM and speech tasks, clears the playback ring and
  discards stale turn IDs. Farewell completion waits for playback to drain.
- A provider failure before any audio permits the existing local fallback. A
  failure after audio starts clears playback and reports a repeat-needed error;
  it never repeats an entire partially spoken medication instruction automatically.
- Kokoro retains its existing whole-clause WAV path. `synthesize_audio` remains a
  complete-WAV compatibility helper for offline fixture/quality tools; live
  Deepgram speech routes through `speak` instead.

The browser HUD reports **Deepgram first audio** for the first clause only
(request to first frame emitted by the server). **Text ready → voice** measures
from the browser's text-complete notice to its worklet-start notice; a negative
export value means speech overlapped text generation. Exports include numeric
buffer-underrun counts. These measure browser rendering notices, not acoustic
speaker output. WAV/browser fallback retains its documented API-start boundary.

The start handshake advertises `pcm_s16le_24000`. Older open tabs that do not
advertise PCM receive WAVs rather than silently ignoring streamed audio. Refresh
a tab after an update to use the latest streaming player.

## Verification

- 90 Python voice/platform/telephony tests passed in network-disabled Docker,
  including eight streaming-specific checks for early delivery, pool reuse,
  cancellation, partial failure, pre-audio fallback, concurrent LLM reading,
  bounded text queues, both phone codecs and decimal-safe clause boundaries.
- 22 browser-controller tests and six playback DSP tests passed, covering stale
  turns, interruption, buffer bounds, malformed formats, farewell drain, a
  continuous 440Hz tone at 44.1/48kHz with jittered arrivals, short responses and
  underrun recovery.
- 20 dashboard tests, lint, TypeScript checking, production build and asset budget
  passed (147.3 KiB initial gzip, 220 KiB budget).
- [Live synthetic provider smoke](../benchmarks/voice/tts-streaming-smoke.json):
  valid 24kHz PCM and 8kHz mu-law arrived incrementally; all HTTP clients closed.
  Browser-format first output was 1,077.9ms versus completion at 4,702.9ms;
  phone-format first output was 959.7ms versus completion at 3,069.3ms. These two
  requests are a format/streaming check, not a controlled performance benchmark.

Run offline checks with the application's validation image and `PLATFORM_ENV=development`:

```sh
python -B -m unittest discover -s tests -p 'test_speech_output.py'
node --test worker-py/tests/call.test.cjs worker-py/tests/playback_worklet.test.cjs
```

For an explicit billable synthetic provider check, supply `DEEPGRAM_API_KEY` in
process environment (never on the command line), and run with `PYTHONPATH=worker-py`:

```sh
python -B scripts/tts_streaming_smoke.py --live --output /tmp/tts-streaming.json
```

A follow-up [Apollo timing check](../benchmarks/voice/tts-text-voice-smoke.json)
measured text completion → first audio at 875.6ms cold and 338.5/243.8ms with a
reused connection. Those three synthetic trials exclude ASR, RAG and browser
buffering. After refreshing the older player, the user confirmed audible Apollo
speech. The continuous worklet replaces that player's per-frame filters and
resamplers, which could introduce chunk-boundary clicks.

After deploying the continuous worklet and refreshing the test page, the user
confirmed that the Deepgram voice sounded clean and the crackling was gone.
Real carrier playback remains unverified. Streaming removes full-response buffering; it does not remove
ASR endpointing, retrieval, LLM first-clause or Deepgram/network latency. Existing
Kokoro/ASR benchmark reports are not relabeled as streaming TTS results.

Provider references: [HTTP audio output streaming](https://developers.deepgram.com/docs/streaming-the-audio-output),
[raw media formats](https://developers.deepgram.com/docs/tts-media-output-settings).
