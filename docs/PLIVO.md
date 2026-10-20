# Plivo telephony and local stream testing

Plivo and Twilio share the managed agent runtime: saved speech recognition
settings/vocabulary, semantic turn completion, approved knowledge retrieval,
response generation, synthesis, interruption and call-history persistence.
Provider signaling is handled separately. No Plivo SDK dependency is required.

## Connect an account

1. In **Connections → Add connection**, choose **Plivo**.
2. Enter a connection name, **Auth ID** and **Auth Token**, then save and test.
   Secrets are encrypted in the existing credential store and are not returned
   to the browser. Connection testing reads the account; it does not place calls.
3. In **Phone numbers → Assign number**, select that connection, enter a
   voice-enabled number owned by the account in E.164 format, and select the
   inbound agent. Assignment does not purchase or provision a number.
4. Publish a tested agent. Direct outbound calls and campaigns use the provider
   associated with their selected caller number. Consent/opt-out checks and
   durable dispatch handling apply to both providers. Campaign execution requires
   a campaign worker built from the same application version; adding a connection
   does not start campaigns. No campaign worker was started during validation.

## Public deployment and inbound calls

Set `PUBLIC_BASE_URL` to the deployment's public HTTPS origin. HTTPS webhooks and
WSS media connections must reach this server; localhost alone cannot receive
provider calls. In Plivo, assign an application to the owned number and set its
Answer URL to HTTP POST:

```text
https://your-server.example/api/plivo/CONNECTION_ID/inbound
```

The phone-number setup dialog displays the appropriate provider URL. Outbound
calls supply their answer, ringing and hangup URLs automatically. V3 signatures
are validated on HTTP callbacks and WebSocket upgrades. Streams must also match
the persisted CallUUID, account Auth ID and one-use token from the signed answer
XML. Only one connection can claim a call. A dispatch RequestUUID is stored
separately; it is never mistaken for the eventual CallUUID.

Audio is mono `audio/x-mulaw;rate=8000`. Other formats are rejected at start
instead of silently decoding them incorrectly. Outbound audio uses `playAudio`,
interruption uses `clearAudio`, and farewell/transfer waits for a matching
`playedStream` checkpoint before provider hangup/transfer. Transfers use signed
Plivo XML with `Dial` and `Speak`. Timeouts with uncertain dispatch outcomes are
recorded for review, never automatically redialed.

These workflows require a usable Plivo account, appropriate account/country
permissions, an allowed caller ID and a reachable deployment. Adding an adapter
does not remove provider trial restrictions or number requirements.

## Number-free local CLI preflight

The CLI produces a **1kHz tone, not spoken questions**. The local endpoint is an
explicit echo preflight for the Plivo transport. It does not send the tone to
ASR, the LLM, RAG or TTS and does not contact Plivo's backend. It is not a clinical
conversation or carrier test. Use the existing browser simulator to speak to the
agent without a telephone number.

1. In a development deployment, set `PLIVO_LOCAL_TEST_ENABLED=1` and restart the
   API. It defaults to `0` in `.env.example` and is always disabled when
   `PLATFORM_ENV=production`, even if the flag is set.
2. Open an agent's **Test agent** page and click **Plivo stream test**.
3. Run the generated command with the official [Plivo CLI](https://www.plivo.com/docs/cli/overview)
   on the computer hosting the development server. On macOS, install it with
   `brew install plivo/tap/plivo` if needed. No Plivo credentials or
   provider phone number are required for this local echo check.
4. The command sends 500 20ms frames over ten seconds and checks that audio
   comes back (`--expect-audio`). Its private URL expires in five minutes and
   works once. Generate a fresh command for another run.

Only authenticated administrators/operators can create test URLs. URL tokens
are hashed in storage and removed from WebSocket access-log scope. Expired,
reused or mismatched tokens are rejected. A completed preflight appears in Call
history with outcome `transport_preflight`, numeric frame counts and no audio or
transcript. It does not mark a draft as conversation-tested for publishing.

The local development container on port 8001 has this flag enabled. Production
Plivo WebSocket endpoints retain signature checks; the local test mode cannot
be used to enter a real call or another workspace.

## Validation

- 91 targeted Python checks passed in a network-disabled Docker image, covering
  Plivo dispatch, signed inbound/answer/status routes, campaign routing, transfer,
  codec rejection, one-use/expired tokens, viewer restrictions, cleanup and
  existing Twilio/voice behavior.
- 20 dashboard checks passed, including the Plivo credential form and local-test
  success/error states. Lint, type checking, production build and bundle budget
  passed.
- The official Plivo CLI v1.2.1 passed a real local WebSocket preflight against
  the final image in a separate synthetic workspace: 500 frames sent/returned,
  zero errors, exit 0, a completed history record and no bearer token in access
  logs. [Saved result](../benchmarks/voice/plivo-local-preflight.json). The 3ms
  echo response is local transport timing, not agent or carrier latency.
- Plivo credentials and a real carrier call have not been supplied for live
  provider validation. Protocol-emulated checks do not close that acceptance gap.

Protocol sources: [stream events](https://docs.plivo.com/docs/voice-agents/audio-streaming/concepts/audio-streaming-reference),
[V3 canonicalization](https://github.com/plivo/plivo-python/blob/master/plivo/utils/signature_v3.py),
[call API](https://docs.plivo.com/docs/voice/api/calls), and
[local tester](https://docs.plivo.com/docs/cli/voice-agent/test-websocket).
