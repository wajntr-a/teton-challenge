#!/usr/bin/env bash
# docker-test.sh — run the full test suite inside Ubuntu 22.04
#
# Builds a test image with swtpm + tpm2-tools + tpm2-openssl + OpenSSL 3,
# then mounts the project directory and runs pytest. Integration tests that
# require tpm2-openssl will run (not skip) inside the container.
#
# Usage:
#   ./scripts/docker-test.sh               # full suite
#   ./scripts/docker-test.sh -k test_hsts  # filter by name
#   ./scripts/docker-test.sh tests/unit/   # run only unit tests

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="teton-challenge-test"

echo "==> Building test image (cached after first run)..."
docker build -f "$PROJECT_ROOT/Dockerfile.test" -t "$IMAGE" "$PROJECT_ROOT"

echo "==> Running tests..."
docker run --rm \
  -v "$PROJECT_ROOT:/project" \
  "$IMAGE" \
  python3 -m pytest tests/ -v "$@"
