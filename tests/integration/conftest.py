"""
Integration test configuration — self-contained swtpm lifecycle.

Starts its own swtpm instance isolated in pytest.tmp_path. Never touches
the demo's /tmp/tpm-state or /tmp/tpm.sock. Generates a test cert chain
inside tmp_path. Tears everything down after each test.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest


def _run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, capture_output=True, **kwargs)


@pytest.fixture
def swtpm_context(tmp_path):
    """
    Start a dedicated swtpm instance for a single integration test.

    Yields a dict:
        {
            "socket":    str  — path to TPM Unix socket
            "state_dir": str  — path to TPM state directory
            "tcti":      str  — TCTI string for tpm2-tools / tpm2-openssl
            "ca_cert":   Path — test CA cert (PEM)
            "ca_key":    Path — test CA key (PEM)
            "device_cert": Path — device cert signed by test CA (PEM)
            "device_key":  Path — device software key (PEM, NOT in TPM)
            "tpm_handle":  str  — persistent handle (0x81000001)
        }

    Env vars TPM2TOOLS_TCTI, TSS2_TCTI, and TPM2OPENSSL_TCTI are set for
    the duration of the test and restored on teardown.
    """
    state_dir = tmp_path / "tpm-state"
    state_dir.mkdir()
    socket_path = tmp_path / "tpm.sock"

    # -----------------------------------------------------------------------
    # Start swtpm
    # -----------------------------------------------------------------------
    proc = subprocess.Popen(
        [
            "swtpm", "socket",
            "--tpmstate", f"dir={state_dir}",
            "--ctrl", f"type=unixio,path={socket_path}",
            "--tpm2",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for socket to appear
    deadline = time.time() + 5.0
    while not socket_path.exists():
        if time.time() > deadline:
            proc.terminate()
            raise RuntimeError("swtpm socket did not appear within 5s")
        time.sleep(0.05)

    tcti = f"swtpm:path={socket_path}"

    # -----------------------------------------------------------------------
    # Set env vars (save originals for restore)
    # -----------------------------------------------------------------------
    env_keys = ["TPM2TOOLS_TCTI", "TSS2_TCTI", "TPM2OPENSSL_TCTI"]
    saved_env = {k: os.environ.get(k) for k in env_keys}
    for k in env_keys:
        os.environ[k] = tcti

    try:
        # -------------------------------------------------------------------
        # Initialize TPM
        # -------------------------------------------------------------------
        _run(["tpm2_startup", "--clear"])

        # -------------------------------------------------------------------
        # Generate and persist RSA key at handle 0x81000001
        # -------------------------------------------------------------------
        primary_ctx = tmp_path / "primary.ctx"
        device_pub  = tmp_path / "device.pub"
        device_priv = tmp_path / "device.priv"
        device_ctx  = tmp_path / "device.ctx"

        _run(["tpm2_createprimary", "-C", "o", "-c", str(primary_ctx)])
        _run([
            "tpm2_create",
            "-C", str(primary_ctx),
            "-G", "rsa2048",
            "-u", str(device_pub),
            "-r", str(device_priv),
        ])
        _run([
            "tpm2_load",
            "-C", str(primary_ctx),
            "-u", str(device_pub),
            "-r", str(device_priv),
            "-c", str(device_ctx),
        ])
        # Evict any existing key at 0x81000001 then persist
        subprocess.run(
            ["tpm2_evictcontrol", "-C", "o", "-c", "0x81000001"],
            capture_output=True,
        )
        _run(["tpm2_evictcontrol", "-C", "o", "-c", str(device_ctx), "0x81000001"])

        # -------------------------------------------------------------------
        # Generate test CA
        # -------------------------------------------------------------------
        ca_key  = tmp_path / "ca.key"
        ca_cert = tmp_path / "ca.crt"
        _run([
            "openssl", "req", "-x509",
            "-newkey", "rsa:2048",
            "-keyout", str(ca_key),
            "-out", str(ca_cert),
            "-days", "1", "-nodes",
            "-subj", "/CN=Test CA",
        ])

        # -------------------------------------------------------------------
        # Create device CSR using TPM key (tpm2-openssl provider)
        # -------------------------------------------------------------------
        device_csr  = tmp_path / "device.csr"
        device_cert = tmp_path / "device.crt"
        san_ext     = tmp_path / "san.ext"
        san_ext.write_text("subjectAltName=DNS:setup.teton-device.local\n")

        _run([
            "openssl", "req",
            "-provider", "tpm2", "-provider", "default",
            "-new",
            "-key", "handle:0x81000001",
            "-subj", "/CN=setup.teton-device.local",
            "-out", str(device_csr),
        ])
        _run([
            "openssl", "x509", "-req",
            "-in", str(device_csr),
            "-CA", str(ca_cert),
            "-CAkey", str(ca_key),
            "-CAcreateserial",
            "-out", str(device_cert),
            "-days", "1", "-sha256",
            "-extfile", str(san_ext),
        ])

        # Use a software key path for the device cert
        # (the private key lives in TPM at 0x81000001 — no file export)
        device_key = Path("handle:0x81000001")

        yield {
            "socket":      str(socket_path),
            "state_dir":   str(state_dir),
            "tcti":        tcti,
            "ca_cert":     ca_cert,
            "ca_key":      ca_key,
            "device_cert": device_cert,
            "device_key":  device_key,
            "tpm_handle":  "0x81000001",
        }

    finally:
        # -------------------------------------------------------------------
        # Teardown: stop swtpm, restore env vars
        # -------------------------------------------------------------------
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
