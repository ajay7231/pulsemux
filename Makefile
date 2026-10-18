.PHONY: all proto build-gateway build-worker test-race up down loadtest

all: proto build-gateway

proto:
	@bash scripts/gen_proto.sh

build-gateway:
	@echo "Building Go Media Gateway..."
	@cd gateway-go && go build -o ../bin/gateway ./cmd/gateway/main.go

PYTHON ?= worker-py/.venv/bin/python

build-worker:
	@echo "Validating Python Worker syntax..."
	@$(PYTHON) -m py_compile worker-py/app/server.py worker-py/app/pipeline/*.py worker-py/app/agent/*.py

test-race:
	@echo "Running Go race detector on audio pipeline..."
	@cd gateway-go && go test -v -race ./internal/audio/...

up:
	@echo "Spinning up PulseMux infrastructure with Docker Compose..."
	@docker compose -f deploy/docker-compose.yml up --build -d

down:
	@docker compose -f deploy/docker-compose.yml down

loadtest:
	@echo "Running concurrency load simulator..."
	@cd loadtest && go run simulator.go -c 20 -d 10

test-pipeline:
	@echo "Running PulseMux Full Stack Voice AI Benchmark..."
	@$(PYTHON) scripts/test_groq_pipeline.py

interactive-pipeline:
	@echo "Starting Interactive Clinical Voice Triage..."
	@$(PYTHON) scripts/test_groq_pipeline.py --interactive

test-groq: test-pipeline
interactive-groq: interactive-pipeline

studio:
	@echo "Starting PulseMux Clinical Voice Studio at http://localhost:8000 ..."
	@$(PYTHON) worker-py/app/web_server.py

ui: studio



