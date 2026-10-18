> **New: Clinical voice operations platform.** Run `make platform` and open
> **http://localhost:8001/dashboard/** to create a hospital workspace, configure
> encrypted provider connections, build and test agents, attach approved knowledge,
> and manage calls and campaigns. See [the platform guide](docs/PLATFORM.md) for
> setup, deployment, architecture, operational limits, and testing. The original
> media-gateway and benchmark documentation is retained below.

# PulseMux: Sub-500ms Bi-Directional Clinical Voice Gateway

[![Go](https://img.shields.io/badge/Go-1.23-00ADD8?logo=go&logoColor=white)](https://golang.org)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![gRPC](https://img.shields.io/badge/gRPC-Bi--Directional-244c5a?logo=grpc)](https://grpc.io)
[![LangGraph](https://img.shields.io/badge/LangGraph-Clinical%20Triage-orange)](https://github.com/langchain-ai/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)

**PulseMux** is an ultra-low-latency, production-grade distributed voice infrastructure engineered for real-time healthcare triage. It decouples high-throughput telephony/WebRTC audio processing from AI orchestration across two specialized planes:

1. **The Go Media & Control Plane (`pulse-gateway`):** In-memory G.711 $\mu$-law/Opus to 16kHz 16-bit PCM transcoding, edge Voice Activity Detection (Silero VAD / adaptive acoustic), 20ms paced ring buffer, and deterministic $<45\text{ms}$ barge-in audio purge.
2. **The Python Intelligence Plane (`pulse-brain`):** High-speed `asyncio`/`uvloop` gRPC server, streaming STT (Deepgram Nova-3), semantic end-of-turn classification, stateful LangGraph clinical workflow with Redis, clause-level streaming TTS (Cartesia/ElevenLabs), and barge-in context truncation reconciliation.

---

## Architecture & Data Flow

```
[Patient Telephony (Twilio/Exotel) or WebRTC Client]
                       │
        (RTP / WebSocket μ-law 8kHz or Opus 48kHz)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ GO MEDIA GATEWAY (Control & Audio Plane)                    │
│  ├─ Ring Buffer & Jitter Control (20ms Ticker Pacing)       │
│  ├─ Audio Resampler (8kHz μ-law ──► 16kHz 16-bit PCM)       │
│  ├─ Local Edge VAD (Silero ONNX / Adaptive Energy Fallback) │
│  └─ Sub-50ms Interrupt Controller (Instant Outbound Purge)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
        (Bi-Directional gRPC Stream: Protobuf Audio/Events)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ PYTHON AI WORKER (Intelligence & Orchestration Plane)       │
│  ├─ Streaming STT Client (Deepgram Nova-3 / Faster-Whisper) │
│  ├─ Speculative Turn Detector (End-of-Thought Classifier)   │
│  ├─ Stateful Clinical Agent (LangGraph + Redis Checkpointer)│
│  └─ Clause-Level Streaming TTS Client (Cartesia Sonic WS)   │
└─────────────────────────────────────────────────────────────┘
```

---

## Production Benchmark SLAs

| Metric | Target SLA | Implementation Guarantee |
| :--- | :--- | :--- |
| **Voice-to-Voice Latency (P50 / P95)** | **$<420\text{ms}$ / $<600\text{ms}$** | Clause-level TTS streaming + speculative turn detection |
| **Barge-In Cancellation Latency** | **$<45\text{ms}$** | In-memory atomic circular buffer purge + `CLEAR_BUFFER` signal |
| **Gateway Concurrency** | **500+ active calls / node** | Zero-copy goroutine concurrency on 4-vCPU, 8GB RAM |
| **Audio Frame Drop Rate** | **$<0.1\%$** | Paced 20ms tickers without disk I/O |

---

## Monorepo Layout

```text
pulsemux/
├── proto/
│   └── voice_stream.proto          # Shared gRPC contract
├── gateway-go/                     # Go Media & Control Plane
│   ├── cmd/gateway/main.go         # HTTP, WebSocket & WebRTC server
│   ├── internal/
│   │   ├── ingress/                # Twilio WS & Pion WebRTC handlers
│   │   ├── audio/                  # Resampler, G.711 μ-law codec, RingBuffer
│   │   ├── vad/                    # VAD state machine & debounce controller
│   │   ├── session/                # Goroutine lifecycle & barge-in controller
│   │   └── rpc/                    # gRPC stream client & event dispatcher
│   ├── models/silero_vad.onnx      # Silero VAD ONNX model directory
│   └── Dockerfile
├── worker-py/                      # Python Intelligence Plane
│   ├── app/
│   │   ├── server.py               # Asyncio gRPC server (uvloop)
│   │   ├── pipeline/
│   │   │   ├── stt_stream.py       # Streaming STT client
│   │   │   ├── turn_detector.py    # Semantic completeness classifier
│   │   │   ├── tts_stream.py       # Clause splitter & streaming TTS
│   │   │   └── canceller.py        # TaskGroup cancellation & context truncation
│   │   └── agent/
│   │       ├── graph.py            # LangGraph clinical triage workflow
│   │       └── tools.py            # EHR slot lookup & red-flag check
│   └── Dockerfile
├── loadtest/                       # Concurrent Call Simulator
│   └── simulator.go                # Twilio WebSocket load generator
├── deploy/
│   ├── docker-compose.yml          # Gateway + Worker + Redis + Prometheus + Jaeger + Grafana
│   ├── grafana-dashboard.json      # Production voice latency dashboard
│   └── prometheus.yml              # Metrics scraping rules
├── scripts/
│   └── gen_proto.sh                # Protocol buffer compilation script
├── Makefile                        # Build and test orchestration
└── README.md
```

---

## Quickstart with Docker Compose

To spin up the entire cluster (Gateway, Worker, Redis, Prometheus, Jaeger, Grafana):

```bash
cd deploy
docker compose up --build -d
```

- **Go Media Gateway:** `http://localhost:8080`
  - Telephony Ingress: `ws://localhost:8080/ws/twilio`
  - WebRTC Signaling: `http://localhost:8080/webrtc/sdp`
  - Health check: `http://localhost:8080/healthz`
- **Prometheus Metrics:** `http://localhost:9090`
- **Jaeger Tracing:** `http://localhost:16686`
- **Grafana Dashboard:** `http://localhost:3000` (User: `admin`, Pass: `admin`)

---

## Running the Concurrency Load Test

Simulate 50 concurrent patient calls with continuous audio streams and barge-in interruptions:

```bash
make loadtest
# Or manually:
cd loadtest && go run simulator.go -c 50 -d 30
```

---

## Profiling with Go `pprof`

To inspect memory allocation and verify flat memory footprint under sustained load:

```bash
go tool pprof http://localhost:8080/debug/pprof/heap
```

---

## Groq Real-World Voice AI Benchmark & Testing

PulseMux is natively integrated with Groq's LPU inference engine for sub-200ms conversational turn latency:
- **Speech-to-Text:** Groq Whisper (`whisper-large-v3-turbo`) transcribes speech turns in ~250ms.
- **Clinical Intelligence:** Groq LLM (`qwen/qwen3.8-27b`) streams triage decisions and emergency evaluations with **<180ms TTFT** (Time To First Token).
- **Clause Splitting:** Real-time syntactic clause punctuation segmentation for continuous streaming TTS audio.

To run the automated clinical scenarios benchmark:
```bash
make test-groq
```

To launch the live interactive voice triage session:
```bash
make interactive-groq
```

---

## 🎙️ Real-Time Browser Clinical Voice Studio

Test live spoken conversation directly inside your browser:
- **ASR:** Deepgram Nova-3 (or Groq Whisper Turbo)
- **Clinical AI:** Groq LPU (`qwen/qwen3.8-27b`)
- **TTS:** Local Kokoro-82M ONNX model (high-fidelity 82M open-weight synthesis)
- **Features:** Start/end call, continuous microphone capture, automatic pause detection, hands-free interruption, mute, live transcripts, noise suppression, and latency telemetry.

To start the studio server:
```bash
make studio
# Or:
make ui
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser, click **Start call**, allow microphone access, and speak naturally. The assistant greets you and listens continuously until you end the call.



The simulator needs no Twilio account or number. It sends Twilio-style `connected`,
`start`, `media`, and `stop` envelopes over `/ws/voice`: mono 8kHz G.711 μ-law,
160 bytes per 20ms frame. The local simulator also sends `speech_start` and
`speech_end` control events; it is not a public Twilio webhook and does not exercise
PSTN routing, carrier latency, or the Go gateway. The existing Go `/ws/twilio`
endpoint remains separate.

Audio capture uses AudioWorklet, browser echo cancellation, optional browser noise
suppression, a telephone bandwidth filter, and an adaptive energy gate. Keep quiet
for the first half-second to calibrate. Six voiced frames (120ms) trigger speech;
a pause of 800ms submits the utterance; continuous speech is split at 20 seconds.
A 300ms pre-roll preserves the beginning of each utterance. Short clicks and steady
room noise are rejected, but energy detection is not a neural speech classifier:
TV voices and loud changing noise can still trigger it. Headphones improve echo
handling. Browser noise suppression support is reported in the UI.

ASR runs on each automatically completed utterance using the selected Deepgram or
Groq provider (Groq is also the fallback if Deepgram fails). Audio frames stream
continuously, but transcription is utterance-based rather than streaming partial
ASR. Provider/network latency still applies; no sub-500ms guarantee is implied.
Configure `DEEPGRAM_API_KEY` and/or `GROQ_API_KEY` in `.env`. Groq is required for
AI-generated answers. Without it, the existing canned responses are used. Local
Kokoro model files are optional: if absent, the simulator reports that it is using
the browser voice. Use localhost or HTTPS for microphone access.

Run simulator regression checks with:
```bash
worker-py/.venv/bin/python -m unittest discover -s worker-py/tests
node --test worker-py/tests/call.test.cjs
```

### Deepgram TTS voices in the simulator

Before starting a call, open **TTS voice** and choose a voice in the
**Deepgram · Aura-2** group: Thalia, Andromeda, Helena, Apollo, Arcas, Aries,
Pandora, or Draco. Kokoro voices remain available in the local group.
The chosen voice is used for the greeting, replies, and goodbye. TTS selection
is independent of ASR selection and is locked during a call.

Deepgram TTS uses the server-side `DEEPGRAM_API_KEY` already used by ASR; the key
must have access to the Speak API and API usage is billed by Deepgram. No SDK or
additional dependency is needed. Each clause is synthesized through
`POST /v1/speak` as 24kHz linear16 WAV, then played through the existing telephone
bandwidth filter. Interruptions cancel outstanding requests and discard queued
audio. On a missing key or API failure, the UI reports a fallback to local
Kokoro/Bella, or the browser voice if Kokoro is unavailable, for the rest of that
call. A new call retries Deepgram.

Voice catalog: https://developers.deepgram.com/docs/tts-models
API format: https://developers.deepgram.com/docs/tts-container
