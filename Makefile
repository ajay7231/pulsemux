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



.PHONY: dashboard-build platform platform-worker platform-test platform-up platform-down

dashboard-build:
	@npm --prefix dashboard ci --no-audit --no-fund
	@npm --prefix dashboard run build

platform: dashboard-build
	@$(PYTHON) -B -m uvicorn app.web_server:app --app-dir worker-py --host 127.0.0.1 --port 8001

platform-worker:
	@cd worker-py && .venv/bin/python -B -m app.platform.jobs

platform-test:
	@$(PYTHON) -B -m unittest discover -s worker-py/tests
	@node --test worker-py/tests/call.test.cjs worker-py/tests/playback_worklet.test.cjs
	@npm --prefix dashboard test
	@npm --prefix dashboard run build

platform-up:
	@docker compose -f deploy/platform-compose.yml up --build -d

platform-down:
	@docker compose -f deploy/platform-compose.yml down

.PHONY: postgres-up postgres-down
postgres-up:
	@$(PYTHON) -B -c 'from pathlib import Path; import secrets; p=Path("worker-py/data/postgres.env"); p.parent.mkdir(parents=True, exist_ok=True, mode=0o700); p.exists() or (p.touch(mode=0o600), p.write_text("POSTGRES_PASSWORD=" + secrets.token_hex(32) + "\n"))'
	@docker compose --env-file worker-py/data/postgres.env -f deploy/postgres-compose.yml up -d --wait

postgres-down:
	@docker compose --env-file worker-py/data/postgres.env -f deploy/postgres-compose.yml down
