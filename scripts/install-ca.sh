#!/usr/bin/env bash
# install-ca.sh — Install Wajntraub demo CA on Ubuntu (Chrome + Firefox)
#
# For the one-machine demo setup where the device and the configurator browser
# run on the same Ubuntu machine. Installs certs/wajntraub-demo-ca.crt into:
#   - The system trust store (picked up by Chrome/Chromium)
#   - Firefox NSS profiles (via certutil)
#
# Idempotent: safe to run multiple times.
# Requires: libnss3-tools (apt install libnss3-tools)
# Run as root (or with sudo).
#
# Other OSes — manual import:
#   Windows:  certmgr.msc → Trusted Root Certification Authorities → Import
#   macOS:    Keychain Access → System → File → Import → set Trust to Always Trust
#   iOS:      Settings → General → VPN & Device Management → Install Profile → trust
#   Android:  Settings → Security → Install from storage → CA certificate

set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
CA_CERT="$(realpath "$SCRIPT_DIR/../certs/wajntraub-demo-ca.crt")"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ ! -f "$CA_CERT" ]]; then
  echo "Error: $CA_CERT not found. Run scripts/setup.sh first."
  exit 1
fi

if ! command -v certutil &>/dev/null; then
  echo "Error: certutil not found. Install libnss3-tools:"
  echo "  apt install libnss3-tools"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Error: this script must be run as root (sudo ./scripts/install-ca.sh)"
  exit 1
fi

# ---------------------------------------------------------------------------
# System trust store (Chrome/Chromium picks this up)
# ---------------------------------------------------------------------------
echo "==> Installing CA cert to system trust store..."
cp "$CA_CERT" /usr/local/share/ca-certificates/wajntraub-demo-ca.crt
update-ca-certificates

# ---------------------------------------------------------------------------
# Firefox NSS profiles
# ---------------------------------------------------------------------------
echo "==> Installing CA cert to Firefox NSS profiles..."
INSTALLED=0

# Support both .default-release (modern) and .default (older) profile dirs
for profile_glob in \
  "$HOME/.mozilla/firefox/*.default-release" \
  "$HOME/.mozilla/firefox/*.default" \
  "/root/.mozilla/firefox/*.default-release" \
  "/root/.mozilla/firefox/*.default"; do
  for profile in $profile_glob; do
    if [[ -d "$profile" ]]; then
      certutil -A -n "Wajntraub Demo CA" -t "CT,," -i "$CA_CERT" -d "$profile"
      echo "  Installed in: $profile"
      INSTALLED=$((INSTALLED + 1))
    fi
  done
done

if [[ $INSTALLED -eq 0 ]]; then
  echo "  No Firefox profiles found — skipping NSS install"
  echo "  (Chrome/Chromium will use the system store installed above)"
fi

echo ""
echo "Done. Restart your browser if it was open."
echo ""
echo "To verify: openssl verify -CAfile $CA_CERT $CA_CERT"
