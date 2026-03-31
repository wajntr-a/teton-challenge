"""
Integration tests for server.py — real swtpm TLS handshake + credential flow.

Uses the swtpm_context fixture from tests/integration/conftest.py which
spins up a dedicated swtpm instance isolated in pytest.tmp_path.

Requires on the host:
  - swtpm
  - tpm2-tools  (tpm2_startup, tpm2_createprimary, …)
  - tpm2-openssl (OpenSSL 3 provider for TPM key access)
  - openssl 3.x

Run as non-root on a high port (4433). The swtpm_context fixture exports
TPM2TOOLS_TCTI, TSS2_TCTI, and TPM2OPENSSL_TCTI for the test process.

Skip automatically if tpm2-openssl provider is unavailable.
"""

import ssl
import threading

import pytest
import requests
import urllib3

import server

# Suppress InsecureRequestWarning for tests that intentionally use a bad CA
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TEST_PORT = 4433
BASE_URL   = f'https://127.0.0.1:{TEST_PORT}'


def _tpm2_openssl_available():
    """Return True if the tpm2 OpenSSL provider can be loaded."""
    import subprocess
    result = subprocess.run(
        ['openssl', 'list', '-providers'],
        capture_output=True, text=True,
    )
    return 'tpm2' in result.stdout.lower()


pytestmark = pytest.mark.skipif(
    not _tpm2_openssl_available(),
    reason='tpm2-openssl provider not available',
)


# ---------------------------------------------------------------------------
# Fixture: running HTTPS server backed by real swtpm TLS
# ---------------------------------------------------------------------------

@pytest.fixture
def live_server(swtpm_context):
    """
    Build a real ssl.SSLContext from the test TPM handle and start
    server.create_server() on TEST_PORT. Yields a dict with:
        {url, ca_cert, credentials, event, server, thread}
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        str(swtpm_context['device_cert']),
        keyfile='handle:0x81000001',
    )

    credentials = {}
    event = threading.Event()
    srv, thread = server.create_server(credentials, event, ctx, port=TEST_PORT)

    yield {
        'url':         BASE_URL,
        'ca_cert':     str(swtpm_context['ca_cert']),
        'credentials': credentials,
        'event':       event,
        'server':      srv,
        'thread':      thread,
    }

    srv.shutdown()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestGetForm:
    def test_returns_200(self, live_server):
        resp = requests.get(
            live_server['url'] + '/',
            verify=live_server['ca_cert'],
        )
        assert resp.status_code == 200

    def test_returns_html_form(self, live_server):
        resp = requests.get(
            live_server['url'] + '/',
            verify=live_server['ca_cert'],
        )
        assert '<form' in resp.text
        assert 'ssid' in resp.text
        assert 'password' in resp.text

    def test_hsts_header_present(self, live_server):
        resp = requests.get(
            live_server['url'] + '/',
            verify=live_server['ca_cert'],
        )
        assert 'Strict-Transport-Security' in resp.headers
        assert 'max-age=31536000' in resp.headers['Strict-Transport-Security']

    def test_rejects_wrong_ca(self, live_server, test_ca, tmp_path):
        """A different CA cert must not validate the server certificate."""
        wrong_ca = test_ca['cert']  # different CA, not the one that signed device cert
        with pytest.raises(requests.exceptions.SSLError):
            requests.get(live_server['url'] + '/', verify=str(wrong_ca))


# ---------------------------------------------------------------------------
# POST /provision — valid credentials
# ---------------------------------------------------------------------------

class TestPostValid:
    def test_returns_200(self, live_server):
        resp = requests.post(
            live_server['url'] + '/provision',
            data={'ssid': 'IntegNet', 'password': 'integ_pw'},
            verify=live_server['ca_cert'],
        )
        assert resp.status_code == 200

    def test_credentials_stored_in_shared_dict(self, live_server):
        requests.post(
            live_server['url'] + '/provision',
            data={'ssid': 'IntegNet', 'password': 'integ_pw'},
            verify=live_server['ca_cert'],
        )
        assert live_server['credentials']['ssid'] == 'IntegNet'
        assert live_server['credentials']['password'] == 'integ_pw'

    def test_event_is_set(self, live_server):
        requests.post(
            live_server['url'] + '/provision',
            data={'ssid': 'IntegNet', 'password': 'integ_pw'},
            verify=live_server['ca_cert'],
        )
        assert live_server['event'].wait(timeout=2), \
            "threading.Event was not set after valid POST"

    def test_hsts_header_present(self, live_server):
        resp = requests.post(
            live_server['url'] + '/provision',
            data={'ssid': 'IntegNet', 'password': 'integ_pw'},
            verify=live_server['ca_cert'],
        )
        assert 'Strict-Transport-Security' in resp.headers


# ---------------------------------------------------------------------------
# POST /provision — invalid credentials
# ---------------------------------------------------------------------------

class TestPostInvalid:
    def test_empty_ssid_returns_400(self, live_server):
        resp = requests.post(
            live_server['url'] + '/provision',
            data={'ssid': '', 'password': 'pw'},
            verify=live_server['ca_cert'],
        )
        assert resp.status_code == 400
        assert not live_server['event'].is_set()

    def test_empty_password_returns_400(self, live_server):
        resp = requests.post(
            live_server['url'] + '/provision',
            data={'ssid': 'Net', 'password': ''},
            verify=live_server['ca_cert'],
        )
        assert resp.status_code == 400
        assert not live_server['event'].is_set()

    def test_hsts_header_on_error(self, live_server):
        resp = requests.post(
            live_server['url'] + '/provision',
            data={'ssid': '', 'password': 'pw'},
            verify=live_server['ca_cert'],
        )
        assert 'Strict-Transport-Security' in resp.headers
