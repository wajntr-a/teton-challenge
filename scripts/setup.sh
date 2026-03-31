#!/usr/bin/env bash
# setup.sh — Teton demo one-time setup
#
# Simulates the Teton manufacturing step on the evaluation machine:
#   1. Starts swtpm (software TPM 2.0)
#   2. Generates the Teton demo CA (evaluator acts as Teton CA)
#   3. Generates an RSA key inside the TPM at persistent handle 0x81000001
#   4. Creates a device CSR from the TPM key and signs it with the demo CA
#
# Idempotent: wipes previous swtpm state and regenerates all certs on each run.
# Run as root (or with sudo) on Ubuntu 22.04+ or Raspberry Pi OS Bookworm.

set -euo pipefail

TPM_STATE_DIR="/tmp/tpm-state"
TPM_SOCK="/tmp/tpm.sock"
CERTS_DIR="$(dirname "$0")/../certs"
CERTS_DIR="$(realpath "$CERTS_DIR")"

# ---------------------------------------------------------------------------
# 1. Stop any swtpm using our socket and wipe state
# ---------------------------------------------------------------------------
echo "==> Stopping any swtpm using $TPM_SOCK..."
if [ -S "$TPM_SOCK" ]; then
    fuser -k "$TPM_SOCK" 2>/dev/null || true
    sleep 0.3
fi

echo "==> Wiping previous swtpm state..."
rm -rf "$TPM_STATE_DIR" "$TPM_SOCK"
mkdir -p "$TPM_STATE_DIR"

# ---------------------------------------------------------------------------
# 2. Start swtpm
# ---------------------------------------------------------------------------
echo "==> Starting swtpm..."
swtpm socket \
  --tpmstate "dir=$TPM_STATE_DIR" \
  --server "type=unixio,path=$TPM_SOCK" \
  --ctrl "type=unixio,path=$TPM_SOCK.ctrl" \
  --tpm2 \
  --flags startup-clear \
  --daemon

sleep 0.5

export TPM2TOOLS_TCTI="swtpm:path=$TPM_SOCK"
export TSS2_TCTI="swtpm:path=$TPM_SOCK"
export TPM2OPENSSL_TCTI="swtpm:path=$TPM_SOCK"

# ---------------------------------------------------------------------------
# 3. Generate RSA key in TPM and persist at handle 0x81000001
# ---------------------------------------------------------------------------
echo "==> Creating primary key (owner hierarchy)..."
tpm2_createprimary -C o -c /tmp/teton-primary.ctx

echo "==> Creating RSA-2048 device key..."
tpm2_create \
  -C /tmp/teton-primary.ctx \
  -G rsa2048 \
  -u /tmp/teton-device.pub \
  -r /tmp/teton-device.priv

echo "==> Loading device key..."
tpm2_load \
  -C /tmp/teton-primary.ctx \
  -u /tmp/teton-device.pub \
  -r /tmp/teton-device.priv \
  -c /tmp/teton-device.ctx

echo "==> Persisting device key at handle 0x81000001..."
# Evict existing key at that handle if present
tpm2_evictcontrol -C o -c 0x81000001 2>/dev/null || true
tpm2_evictcontrol -C o -c /tmp/teton-device.ctx 0x81000001

# ---------------------------------------------------------------------------
# 4. Generate Teton demo CA
# ---------------------------------------------------------------------------
echo "==> Generating Teton demo CA..."
mkdir -p "$CERTS_DIR"
openssl req -x509 -newkey rsa:4096 \
  -keyout "$CERTS_DIR/teton-ca.key" \
  -out    "$CERTS_DIR/teton-ca.crt" \
  -days 3650 -nodes \
  -subj "/CN=Teton Demo CA/O=Teton AI"

# ---------------------------------------------------------------------------
# 5. Create device CSR using the TPM key (via tpm2-openssl provider)
# ---------------------------------------------------------------------------
echo "==> Creating device CSR using TPM key (tpm2-openssl provider)..."
openssl req \
  -provider tpm2 -provider default \
  -new \
  -key "handle:0x81000001" \
  -subj "/CN=setup.teton-device.local" \
  -out /tmp/teton-device.csr

# ---------------------------------------------------------------------------
# 6. Sign device CSR with demo CA (add SAN — required by modern browsers)
# ---------------------------------------------------------------------------
echo "==> Signing device CSR with Teton demo CA..."
openssl x509 -req \
  -in /tmp/teton-device.csr \
  -CA    "$CERTS_DIR/teton-ca.crt" \
  -CAkey "$CERTS_DIR/teton-ca.key" \
  -CAcreateserial \
  -out "$CERTS_DIR/device.crt" \
  -days 365 -sha256 \
  -extfile <(printf "subjectAltName=DNS:setup.teton-device.local\n")

# ---------------------------------------------------------------------------
# 7. Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verifying cert chain..."
openssl verify -CAfile "$CERTS_DIR/teton-ca.crt" "$CERTS_DIR/device.crt"

echo ""
echo "Setup complete."
echo "  swtpm socket: $TPM_SOCK"
echo "  TPM handle:   0x81000001 (private key never exported)"
echo "  CA cert:      $CERTS_DIR/teton-ca.crt"
echo "  Device cert:  $CERTS_DIR/device.crt"
echo ""
echo "Next: sudo ./scripts/install-ca.sh"
