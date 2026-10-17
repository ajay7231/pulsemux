# Stage 1: Builder
FROM golang:1.23-bookworm AS builder

WORKDIR /app

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy go.mod first and tidy to generate/verify go.sum inside the container
COPY go.mod ./
RUN go mod tidy 2>/dev/null || true

# Copy full source
COPY . .

# Tidy again now that all source files are present (resolves all imports)
RUN go mod tidy

# Build static binary — CGO disabled for portable boilerplate
# (re-enable with CGO_ENABLED=1 when linking the Silero ONNX runtime)
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/gateway ./cmd/gateway/main.go

# Stage 2: Minimal scratch-based runtime (static binary needs no libc)
FROM gcr.io/distroless/static-debian12

WORKDIR /app

COPY --from=builder /bin/gateway /app/gateway

EXPOSE 8080

CMD ["/app/gateway"]
