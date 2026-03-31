"""
Unit tests for server.py — credential validation and HSTS header.

Uses Flask's test client via server.create_app(). No real HTTPS server or
thread is started. shutdown_callback is a plain MagicMock.
"""

import threading
from unittest.mock import MagicMock

import pytest

import server


@pytest.fixture
def app_context():
    """Return a fresh (credentials, event, mock_shutdown, Flask test client)."""
    credentials = {}
    event = threading.Event()
    mock_shutdown = MagicMock()
    app = server.create_app(credentials, event, shutdown_callback=mock_shutdown)
    app.config['TESTING'] = True
    client = app.test_client()
    return {
        'credentials': credentials,
        'event': event,
        'shutdown': mock_shutdown,
        'client': client,
    }


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestGetForm:
    def test_returns_200(self, app_context):
        resp = app_context['client'].get('/')
        assert resp.status_code == 200

    def test_returns_html_form(self, app_context):
        resp = app_context['client'].get('/')
        html = resp.data.decode()
        assert '<form' in html
        assert 'ssid' in html
        assert 'password' in html

    def test_hsts_header_present(self, app_context):
        resp = app_context['client'].get('/')
        assert 'Strict-Transport-Security' in resp.headers
        assert 'max-age=31536000' in resp.headers['Strict-Transport-Security']


# ---------------------------------------------------------------------------
# POST /provision — valid input
# ---------------------------------------------------------------------------

class TestPostValid:
    def test_returns_200(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': 'secret'}
        )
        assert resp.status_code == 200

    def test_credentials_stored_in_shared_dict(self, app_context):
        app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': 'secret'}
        )
        assert app_context['credentials']['ssid'] == 'MyNet'
        assert app_context['credentials']['password'] == 'secret'

    def test_event_is_set(self, app_context):
        app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': 'secret'}
        )
        assert app_context['event'].is_set()

    def test_shutdown_callback_invoked(self, app_context):
        app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': 'secret'}
        )
        app_context['shutdown'].assert_called_once()

    def test_hsts_header_present(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': 'secret'}
        )
        assert 'Strict-Transport-Security' in resp.headers
        assert 'max-age=31536000' in resp.headers['Strict-Transport-Security']


# ---------------------------------------------------------------------------
# POST /provision — invalid input
# ---------------------------------------------------------------------------

class TestPostInvalid:
    def _assert_no_side_effects(self, ctx):
        assert ctx['credentials'] == {}, "credentials must not be stored on error"
        assert not ctx['event'].is_set(), "event must not be set on error"
        ctx['shutdown'].assert_not_called()

    def test_empty_ssid_returns_error(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': '', 'password': 'secret'}
        )
        assert resp.status_code == 400
        self._assert_no_side_effects(app_context)

    def test_empty_password_returns_error(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': 'MyNet', 'password': ''}
        )
        assert resp.status_code == 400
        self._assert_no_side_effects(app_context)

    def test_missing_ssid_returns_error(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'password': 'secret'}
        )
        assert resp.status_code == 400
        self._assert_no_side_effects(app_context)

    def test_missing_password_returns_error(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': 'MyNet'}
        )
        assert resp.status_code == 400
        self._assert_no_side_effects(app_context)

    def test_error_response_contains_reason(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': '', 'password': 'secret'}
        )
        html = resp.data.decode()
        assert len(html) > 0, "error response body must not be empty"

    def test_hsts_header_on_error(self, app_context):
        resp = app_context['client'].post(
            '/provision', data={'ssid': '', 'password': 'secret'}
        )
        assert 'Strict-Transport-Security' in resp.headers
        assert 'max-age=31536000' in resp.headers['Strict-Transport-Security']
