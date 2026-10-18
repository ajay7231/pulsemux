ARG BASE_IMAGE=pulsemux-platform:latest
FROM ${BASE_IMAGE}
COPY scripts/voice_latency_baseline.py /app/benchmarks/voice_latency_baseline.py
COPY scripts/score_voice_baseline.py /app/benchmarks/score_voice_baseline.py
COPY benchmarks/voice/scenarios.json /app/benchmarks/voice/scenarios.json
COPY benchmarks/voice/normalization.json /app/benchmarks/voice/normalization.json
