.PHONY: all proto build-gateway build-worker test-race up down loadtest

all: proto build-gateway

proto:
	@bash scripts/gen_proto.sh

build-gateway:
	@echo "Building Go Media Gateway..."
	@cd gateway-go && go build -o ../bin/gateway ./cmd/gateway/main.go

build-worker:
	@echo "Validating Python Worker syntax..."
	@python3 -m py_compile worker-py/app/server.py worker-py/app/pipeline/*.py worker-py/app/agent/*.py

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
