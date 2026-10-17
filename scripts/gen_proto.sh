#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$ROOT_DIR/proto"

echo "=== Generating Protocol Buffers for PulseMux ==="

# Target directories
GO_OUT="$ROOT_DIR/gateway-go/gen"
PY_OUT="$ROOT_DIR/worker-py/app"

mkdir -p "$GO_OUT" "$PY_OUT"

# 1. Generate Python gRPC Stubs
if command -v python3 &>/dev/null; then
    echo "[+] Generating Python stubs in $PY_OUT..."
    python3 -m grpc_tools.protoc \
        -I"$PROTO_DIR" \
        --python_out="$PY_OUT" \
        --grpc_python_out="$PY_OUT" \
        "$PROTO_DIR/voice_stream.proto" || echo "[!] Notice: Install grpcio-tools (pip install grpcio-tools) to regenerate Python stubs."
fi

# 2. Generate Go gRPC Stubs
if command -v protoc &>/dev/null; then
    echo "[+] Generating Go stubs in $GO_OUT..."
    protoc \
        --proto_path="$PROTO_DIR" \
        --go_out="$GO_OUT" --go_opt=paths=source_relative \
        --go-grpc_out="$GO_OUT" --go-grpc_opt=paths=source_relative \
        "$PROTO_DIR/voice_stream.proto" || echo "[!] Notice: Ensure protoc-gen-go and protoc-gen-go-grpc are installed in PATH."
else
    echo "[i] protoc not installed in local environment. Docker build will compile stubs in containerized environments."
fi

echo "=== Protobuf generation step complete ==="
