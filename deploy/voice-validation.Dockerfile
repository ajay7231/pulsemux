ARG BASE_IMAGE=pulsemux-platform:latest
FROM ${BASE_IMAGE}
COPY scripts/ /app/scripts/
COPY benchmarks/voice/*.json /app/benchmarks/voice/
COPY worker-py/tests/ /app/tests/
ENV PYTHONPATH=/app
