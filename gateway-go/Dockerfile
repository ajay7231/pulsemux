# Stage 1: Builder
FROM golang:1.23-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    protobuf-compiler \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Cache dependencies
COPY go.mod ./
# If go.sum exists, copy it
RUN go mod download || true

# Copy source code
COPY . .

# Build gateway binary
RUN CGO_ENABLED=1 GOOS=linux go build -o /bin/gateway ./cmd/gateway/main.go

# Stage 2: Runtime
FROM debian:bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /bin/gateway /app/gateway

EXPOSE 8080

CMD ["/app/gateway"]
