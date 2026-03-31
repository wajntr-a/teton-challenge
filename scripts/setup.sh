#!/usr/bin/env bash
# setup.sh — Wajntraub demo one-time setup
#
# Simulates the manufacturing step on the evaluation machine:
#   1. Starts swtpm (software TPM 2.0)
#   2. Generates the Wajntraub demo CA (evaluator acts as demo CA)
#   3. Generates an RSA key inside the TPM at persistent handle 0x81000001
#   4. Creates a device CSR from the TPM key and signs it with the demo CA
#
# Idempotent: wipes previous swtpm state and regenerates all certs on each run.
# Run as root (or with sudo) on Ubuntu 22.04+ or Raspberry Pi OS Bookworm.
#
# Usage:
#   sudo ./scripts/setup.sh                  # full setup (new CA + new device cert)
#   sudo ./scripts/setup.sh --new-device-cert  # new device cert only, reuse existing CA
#   sudo ./scripts/setup.sh --clean          # remove all generated artefacts

set -euo pipefail

TPM_STATE_DIR="/tmp/tpm-state"
TPM_SOCK="/tmp/tpm.sock"
CERTS_DIR="$(dirname "$0")/../certs"
CERTS_DIR="$(realpath "$CERTS_DIR")"
DEMO_PREFIX="wajntraub-demo"

# ---------------------------------------------------------------------------
# --new-device-cert: reuse existing CA, generate new device key + cert only
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--new-device-cert" ]; then
    if [ ! -f "$CERTS_DIR/wajntraub-demo-ca.key" ] || [ ! -f "$CERTS_DIR/wajntraub-demo-ca.crt" ]; then
        echo "ERROR: CA not found in $CERTS_DIR — run setup.sh without arguments first."
        exit 1
    fi

    echo "==> Generating new software device key..."
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
    # -----------------------------------------------------------------------
    # List everything that will be removed, then ask for confirmation
    # -----------------------------------------------------------------------
    echo "The following artefacts will be removed:"
    echo ""

    _found=0
    for f in \
        "$TPM_STATE_DIR" \
        "$TPM_SOCK" "$TPM_SOCK.ctrl" \
        /tmp/wajntraub-demo-primary.ctx \
        /tmp/wajntraub-demo-device.pub \
        /tmp/wajntraub-demo-device.priv \
        /tmp/wajntraub-demo-device.ctx \
        /tmp/wajntraub-demo-device.csr \
        "$CERTS_DIR/wajntraub-demo-ca.key" \
        "$CERTS_DIR/wajntraub-demo-ca.crt" \
        "$CERTS_DIR/wajntraub-demo-ca.srl" \
        "$CERTS_DIR/device.key" \
        "$CERTS_DIR/device.crt"
    do
        if [ -e "$f" ] || [ -S "$f" ]; then
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
    echo "==> Stopping any swtpm using $TPM_SOCK..."
    if [ -S "$TPM_SOCK" ]; then
        fuser -k "$TPM_SOCK" 2>/dev/null || true
        sleep 0.3
    fi

    echo "==> Removing swtpm state and sockets..."
    rm -rf "$TPM_STATE_DIR" "$TPM_SOCK" "$TPM_SOCK.ctrl"

    echo "==> Removing temporary TPM work files..."
    rm -f /tmp/wajntraub-demo-primary.ctx \
          /tmp/wajntraub-demo-device.pub \
          /tmp/wajntraub-demo-device.priv \
          /tmp/wajntraub-demo-device.ctx \
          /tmp/wajntraub-demo-device.csr

    echo "==> Removing generated certificates..."
    rm -f "$CERTS_DIR/wajntraub-demo-ca.key" \
          "$CERTS_DIR/wajntraub-demo-ca.crt" \
          "$CERTS_DIR/wajntraub-demo-ca.srl" \
          "$CERTS_DIR/device.key" \
          "$CERTS_DIR/device.crt"
    # Remove certs/ dir if now empty
    rmdir "$CERTS_DIR" 2>/dev/null || true

    echo "Clean complete."
    exit 0
fi

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

export TPM2TOOLS_TCTI="swtpm:path=$TPM_SOCK"
export TSS2_TCTI="swtpm:path=$TPM_SOCK"
export TPM2OPENSSL_TCTI="swtpm:path=$TPM_SOCK"

echo "==> Waiting for swtpm to be ready..."
_ready=0
for _i in $(seq 1 20); do
    if timeout 1 tpm2_getcap properties-fixed >/dev/null 2>&1; then
        _ready=1
        break
    fi
    sleep 0.3
done
if [ "$_ready" -eq 0 ]; then
    echo "ERROR: swtpm did not become ready after 6 seconds"
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Generate RSA key in TPM and persist at handle 0x81000001
# ---------------------------------------------------------------------------
echo "==> Flushing any existing TPM transient handles..."
tpm2_getcap handles-transient 2>/dev/null \
  | grep -oE '0x[0-9a-fA-F]+' \
  | xargs -r -I{} tpm2_flushcontext {} \
  || true

echo "==> Creating primary key (owner hierarchy)..."
tpm2_createprimary -C o -c /tmp/wajntraub-demo-primary.ctx

echo "==> Flushing transients before tpm2_create..."
tpm2_getcap handles-transient 2>/dev/null \
  | grep -oE '0x[0-9a-fA-F]+' \
  | xargs -r -I{} tpm2_flushcontext {} \
  || true

echo "==> Creating RSA-2048 device key..."
tpm2_create \
  -C /tmp/wajntraub-demo-primary.ctx \
  -G rsa2048 \
  -u /tmp/wajntraub-demo-device.pub \
  -r /tmp/wajntraub-demo-device.priv

echo "==> Flushing transients before tpm2_load..."
tpm2_getcap handles-transient 2>/dev/null \
  | grep -oE '0x[0-9a-fA-F]+' \
  | xargs -r -I{} tpm2_flushcontext {} \
  || true

echo "==> Loading device key..."
tpm2_load \
  -C /tmp/wajntraub-demo-primary.ctx \
  -u /tmp/wajntraub-demo-device.pub \
  -r /tmp/wajntraub-demo-device.priv \
  -c /tmp/wajntraub-demo-device.ctx

echo "==> Persisting device key at handle 0x81000001..."
# Evict existing key at that handle if present
tpm2_evictcontrol -C o -c 0x81000001 2>/dev/null || true
tpm2_evictcontrol -C o -c /tmp/wajntraub-demo-device.ctx 0x81000001

# ---------------------------------------------------------------------------
# 4. Generate Wajntraub demo CA
# ---------------------------------------------------------------------------
echo "==> Generating Wajntraub demo CA..."
mkdir -p "$CERTS_DIR"
openssl req -x509 -newkey rsa:4096 \
  -keyout "$CERTS_DIR/wajntraub-demo-ca.key" \
  -out    "$CERTS_DIR/wajntraub-demo-ca.crt" \
  -days 3650 -nodes \
  -subj "/CN=Wajntraub Demo CA/O=Wajntraub Demo"

# ---------------------------------------------------------------------------
# 5. Generate software device key and create CSR
#
# NOTE: Python's ssl.SSLContext.load_cert_chain() calls OpenSSL's
# SSL_CTX_use_PrivateKey_file() which uses fopen() and cannot resolve TPM
# store URIs like "handle:0x81000001". The tpm2-openssl provider hooks into
# OpenSSL's OSSL_STORE API, which Python's stdlib ssl module never invokes.
#
# The production fix is tpm2-pkcs11 (PKCS#11 engine over TPM2), which IS
# reachable from Python ssl. For this demo, we use a software RSA key for
# TLS termination. The TPM key at 0x81000001 is still generated and
# persisted above — demonstrating the manufacturing provisioning step —
# but TLS uses this software key.
# ---------------------------------------------------------------------------
echo "==> Generating software device key for TLS..."
openssl genrsa -out "$CERTS_DIR/device.key" 2048

echo "==> Creating device CSR..."
openssl req -new \
  -key "$CERTS_DIR/device.key" \
  -subj "/CN=setup.wajntraub-demo.local" \
  -out /tmp/wajntraub-demo-device.csr

# ---------------------------------------------------------------------------
# 6. Sign device CSR with demo CA (add SAN — required by modern browsers)
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
# 7. Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verifying cert chain..."
openssl verify -CAfile "$CERTS_DIR/wajntraub-demo-ca.crt" "$CERTS_DIR/device.crt"

echo ""
echo "Setup complete."
echo "  swtpm socket: $TPM_SOCK"
echo "  TPM handle:   0x81000001 (identity key — never exported)"
echo "  CA cert:      $CERTS_DIR/wajntraub-demo-ca.crt"
echo "  Device cert:  $CERTS_DIR/device.crt"
echo "  Device key:   $CERTS_DIR/device.key  (software key for TLS)"
echo ""
echo "  NOTE: TLS uses a software key. Production would use tpm2-pkcs11."
echo ""
echo "Next: sudo ./scripts/install-ca.sh"
