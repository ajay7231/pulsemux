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
