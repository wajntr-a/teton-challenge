#!/usr/bin/env bash
# setup.sh — Wajntraub demo one-time setup
#
# Simulates the manufacturing step on the evaluation machine:
#   1. Generates the Wajntraub demo CA
#   2. Generates a software RSA key and issues the device certificate
#
# Idempotent: regenerates all certs on each run.
# Run as root (or with sudo) on any Ubuntu or Raspberry Pi OS.
#
# Usage:
#   sudo ./scripts/setup.sh                    # full setup (new CA + new device cert)
#   sudo ./scripts/setup.sh --new-device-cert  # new device cert only, reuse existing CA
#   sudo ./scripts/setup.sh --clean            # remove all generated artefacts

set -euo pipefail

CERTS_DIR="$(dirname "$0")/../certs"
CERTS_DIR="$(realpath "$CERTS_DIR")"

# ---------------------------------------------------------------------------
# --new-device-cert: reuse existing CA, generate new device key + cert only
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--new-device-cert" ]; then
    if [ ! -f "$CERTS_DIR/wajntraub-demo-ca.key" ] || [ ! -f "$CERTS_DIR/wajntraub-demo-ca.crt" ]; then
        echo "ERROR: CA not found in $CERTS_DIR — run setup.sh without arguments first."
        exit 1
    fi

    echo "==> Generating new device key..."
    openssl genrsa -out "$CERTS_DIR/device.key" 2048

    echo "==> Creating device CSR..."
    openssl req -new \
      -key "$CERTS_DIR/device.key" \
      -subj "/CN=setup.wajntraub-demo.local" \
      -out /tmp/wajntraub-demo-device.csr

    echo "==> Signing device CSR with existing Wajntraub demo CA..."
    openssl x509 -req \
      -in /tmp/wajntraub-demo-device.csr \
      -CA    "$CERTS_DIR/wajntraub-demo-ca.crt" \
      -CAkey "$CERTS_DIR/wajntraub-demo-ca.key" \
      -CAcreateserial \
      -out "$CERTS_DIR/device.crt" \
      -days 365 -sha256 \
      -extfile <(printf "subjectAltName=DNS:setup.wajntraub-demo.local\n")

    echo "==> Verifying cert chain..."
    openssl verify -CAfile "$CERTS_DIR/wajntraub-demo-ca.crt" "$CERTS_DIR/device.crt"

    echo ""
    echo "New device cert generated."
    echo "  Device cert: $CERTS_DIR/device.crt"
    echo "  Device key:  $CERTS_DIR/device.key"
    echo "  CA cert:     $CERTS_DIR/wajntraub-demo-ca.crt  (unchanged — no browser re-import needed)"
    exit 0
fi

# ---------------------------------------------------------------------------
# --clean: remove all artefacts produced by this script and exit
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--clean" ]; then
    echo "The following artefacts will be removed:"
    echo ""

    _found=0
    for f in \
        /tmp/wajntraub-demo-device.csr \
        "$CERTS_DIR/wajntraub-demo-ca.key" \
        "$CERTS_DIR/wajntraub-demo-ca.crt" \
        "$CERTS_DIR/wajntraub-demo-ca.srl" \
        "$CERTS_DIR/device.key" \
        "$CERTS_DIR/device.crt"
    do
        if [ -e "$f" ]; then
            echo "  $f"
            _found=$((_found + 1))
        fi
    done

    if [ "$_found" -eq 0 ]; then
        echo "  (nothing to remove)"
        echo ""
        echo "Nothing to clean."
        exit 0
    fi

    echo ""
    printf "Proceed? [y/N] "
    read -r _reply
    if [ "$_reply" != "y" ] && [ "$_reply" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi

    echo ""
    echo "==> Removing generated certificates..."
    rm -f /tmp/wajntraub-demo-device.csr \
          "$CERTS_DIR/wajntraub-demo-ca.key" \
          "$CERTS_DIR/wajntraub-demo-ca.crt" \
          "$CERTS_DIR/wajntraub-demo-ca.srl" \
          "$CERTS_DIR/device.key" \
          "$CERTS_DIR/device.crt"
    rmdir "$CERTS_DIR" 2>/dev/null || true

    echo "Clean complete."
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Generate Wajntraub demo CA
# ---------------------------------------------------------------------------
echo "==> Generating Wajntraub demo CA..."
mkdir -p "$CERTS_DIR"
openssl req -x509 -newkey rsa:4096 \
  -keyout "$CERTS_DIR/wajntraub-demo-ca.key" \
  -out    "$CERTS_DIR/wajntraub-demo-ca.crt" \
  -days 3650 -nodes \
  -subj "/CN=Wajntraub Demo CA/O=Wajntraub Demo"

# ---------------------------------------------------------------------------
# 2. Generate device key and CSR
# ---------------------------------------------------------------------------
echo "==> Generating device key..."
openssl genrsa -out "$CERTS_DIR/device.key" 2048

echo "==> Creating device CSR..."
openssl req -new \
  -key "$CERTS_DIR/device.key" \
  -subj "/CN=setup.wajntraub-demo.local" \
  -out /tmp/wajntraub-demo-device.csr

# ---------------------------------------------------------------------------
# 3. Sign device CSR with demo CA (SAN required by modern browsers)
# ---------------------------------------------------------------------------
echo "==> Signing device CSR with Wajntraub demo CA..."
openssl x509 -req \
  -in /tmp/wajntraub-demo-device.csr \
  -CA    "$CERTS_DIR/wajntraub-demo-ca.crt" \
  -CAkey "$CERTS_DIR/wajntraub-demo-ca.key" \
  -CAcreateserial \
  -out "$CERTS_DIR/device.crt" \
  -days 365 -sha256 \
  -extfile <(printf "subjectAltName=DNS:setup.wajntraub-demo.local\n")

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verifying cert chain..."
openssl verify -CAfile "$CERTS_DIR/wajntraub-demo-ca.crt" "$CERTS_DIR/device.crt"

echo ""
echo "Setup complete."
echo "  CA cert:     $CERTS_DIR/wajntraub-demo-ca.crt"
echo "  Device cert: $CERTS_DIR/device.crt"
echo "  Device key:  $CERTS_DIR/device.key"
echo ""
echo "Next: sudo ./scripts/install-ca.sh"
