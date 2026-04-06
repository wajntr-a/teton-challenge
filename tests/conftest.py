"""
Root test configuration.

- Inserts device/ into sys.path so all test files can import wifi, server,
  and provision without package qualification.
- Provides shared cert generation fixtures for unit tests.
"""

import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path injection — must happen at import time
# ---------------------------------------------------------------------------
_DEVICE_DIR = str(Path(__file__).parent.parent / "device")
if _DEVICE_DIR not in sys.path:
    sys.path.insert(0, _DEVICE_DIR)


# ---------------------------------------------------------------------------
# Cert generation helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_ca(tmp_path):
    """
    Generate a short-lived self-signed test CA in tmp_path.
    Returns {"cert": Path, "key": Path}.
    """
    key = tmp_path / "ca.key"
    cert = tmp_path / "ca.crt"
    subprocess.run(
        [
            "openssl", "req", "-x509",
            "-newkey", "rsa:2048",
            "-keyout", str(key),
            "-out", str(cert),
            "-days", "1",
            "-nodes",
            "-subj", "/CN=Test CA",
        ],
        check=True,
        capture_output=True,
    )
    return {"cert": cert, "key": key}


@pytest.fixture
def test_device_cert(tmp_path, test_ca):
    """
    Generate a test device cert signed by test_ca in tmp_path.
    CN=setup.wajntraub-demo.local with SAN extension.
    Returns {"cert": Path, "key": Path}.
    """
    key = tmp_path / "device.key"
    csr = tmp_path / "device.csr"
    cert = tmp_path / "device.crt"
    ext = tmp_path / "san.ext"

    ext.write_text("subjectAltName=DNS:setup.wajntraub-demo.local\n")

    subprocess.run(
        ["openssl", "genrsa", "-out", str(key), "2048"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl", "req", "-new",
            "-key", str(key),
            "-out", str(csr),
            "-subj", "/CN=setup.wajntraub-demo.local",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl", "x509", "-req",
            "-in", str(csr),
            "-CA", str(test_ca["cert"]),
            "-CAkey", str(test_ca["key"]),
            "-CAcreateserial",
            "-out", str(cert),
            "-days", "1",
            "-sha256",
            "-extfile", str(ext),
        ],
        check=True,
        capture_output=True,
    )
    return {"cert": cert, "key": key}
