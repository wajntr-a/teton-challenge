"""
Unit tests for provision.py — state machine transitions.

All external dependencies are mocked:
  - provision._start_swtpm     → returns a mock process
  - provision._load_ssl_context → returns a mock ssl context
  - provision._swtpm_alive      → controls swtpm health
  - wifi.start_ap / wifi.stop_ap / wifi.connect
  - server.create_server

Tests drive provision.run() and verify the observed call sequence and
final state rather than inspecting internal state variables.
"""

import subprocess
import threading
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

import provision
from provision import ProvisionState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_server_factory(ssid='TestNet', password='testpw', set_event=True):
    """
    Return a create_server side_effect that optionally fills credentials and
    sets the event synchronously (simulating a successful POST /provision).
    """
    def _factory(credentials, event, ssl_ctx, port=443):
        mock_srv = MagicMock()
        mock_thread = MagicMock()
        if set_event:
            credentials['ssid'] = ssid
            credentials['password'] = password
            event.set()
        return mock_srv, mock_thread
    return _factory


@contextmanager
def _apply_patches(patches):
    """Apply a dict of {patch_target: mock} across multiple modules."""
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        yield patches


def _base_patches(set_event=True, swtpm_alive=True, connect_raises=False):
    """Return a dict of patch kwargs covering the full happy path."""
    return {
        'provision._start_swtpm': MagicMock(return_value=MagicMock()),
        'provision._load_ssl_context': MagicMock(return_value=MagicMock()),
        'provision._swtpm_alive': MagicMock(return_value=swtpm_alive),
        'wifi.start_ap': MagicMock(),
        'wifi.stop_ap': MagicMock(),
        'wifi.connect': MagicMock(
            side_effect=subprocess.CalledProcessError(1, 'nmcli') if connect_raises else None
        ),
        'server.create_server': MagicMock(
            side_effect=_make_server_factory(set_event=set_event)
        ),
    }


# ---------------------------------------------------------------------------
# INIT → AP_MODE
# ---------------------------------------------------------------------------

class TestInitToApMode:
    def test_ssl_context_loaded_in_init(self):
        patches = _base_patches()
        with _apply_patches(patches):
            provision.run()
        patches['provision._load_ssl_context'].assert_called_once()

    def test_swtpm_started_in_init(self):
        patches = _base_patches()
        with _apply_patches(patches):
            provision.run()
        patches['provision._start_swtpm'].assert_called_once()

    def test_start_ap_called_on_ap_mode_entry(self):
        patches = _base_patches()
        with _apply_patches(patches):
            provision.run()
        patches['wifi.start_ap'].assert_called()

    def test_create_server_called_on_ap_mode_entry(self):
        patches = _base_patches()
        with _apply_patches(patches):
            provision.run()
        patches['server.create_server'].assert_called()


# ---------------------------------------------------------------------------
# AP_MODE → PROVISIONED → CONNECTING → ONLINE
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_connect_called_with_credentials(self):
        patches = _base_patches(set_event=True)
        with _apply_patches(patches):
            provision.run()
        patches['wifi.connect'].assert_called_once_with('TestNet', 'testpw')

    def test_ssl_context_reused_not_rebuilt_on_second_ap_entry(self):
        """ssl.SSLContext is constructed once in INIT; reused on retry."""
        # First attempt: nmcli fails → ERROR → AP_MODE retry → success
        call_count = {'n': 0}
        def connect_first_fails(*a, **kw):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise subprocess.CalledProcessError(1, 'nmcli')

        patches = _base_patches()
        patches['wifi.connect'] = MagicMock(side_effect=connect_first_fails)
        with _apply_patches(patches):
            provision.run()

        # _load_ssl_context must only be called once (INIT), not on retry
        patches['provision._load_ssl_context'].assert_called_once()

    def test_server_thread_joined_before_connect(self):
        """provision.py joins the server thread after event fires, before wifi.connect."""
        join_order = []
        mock_thread = MagicMock()
        mock_thread.join.side_effect = lambda: join_order.append('join')

        def fake_create(credentials, event, ssl_ctx, port=443):
            credentials['ssid'] = 'Net'
            credentials['password'] = 'pw'
            event.set()
            return MagicMock(), mock_thread

        patches = _base_patches()
        patches['server.create_server'] = MagicMock(side_effect=fake_create)
        patches['wifi.connect'] = MagicMock(
            side_effect=lambda *a, **kw: join_order.append('connect')
        )
        with _apply_patches(patches):
            provision.run()

        assert join_order.index('join') < join_order.index('connect'), \
            "thread.join() must happen before wifi.connect()"


# ---------------------------------------------------------------------------
# AP_MODE timeout → ERROR
# ---------------------------------------------------------------------------

class TestApModeTimeout:
    def test_error_on_timeout(self):
        """event.wait() returning False (timeout) transitions to ERROR."""
        patches = _base_patches(set_event=False)  # event never fires → timeout

        # Make event.wait() return False immediately to avoid 600s wait
        real_create = patches['server.create_server'].side_effect
        def fast_timeout(credentials, event, ssl_ctx, port=443):
            srv, thread = MagicMock(), MagicMock()
            # Patch event.wait so it returns False (timeout) instantly
            event.wait = MagicMock(return_value=False)
            return srv, thread

        patches['server.create_server'] = MagicMock(side_effect=fast_timeout)

        with _apply_patches(patches):
            provision.run()

        # connect must never be called on timeout path
        patches['wifi.connect'].assert_not_called()


# ---------------------------------------------------------------------------
# CONNECTING → ERROR → AP_MODE retry
# ---------------------------------------------------------------------------

class TestRetry:
    def test_retry_on_nmcli_failure(self):
        """nmcli failure → ERROR → AP_MODE retry (one time)."""
        call_count = {'n': 0}
        def connect_first_fails(*a, **kw):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise subprocess.CalledProcessError(1, 'nmcli')

        patches = _base_patches()
        patches['wifi.connect'] = MagicMock(side_effect=connect_first_fails)
        with _apply_patches(patches):
            provision.run()

        assert patches['wifi.connect'].call_count == 2, \
            "connect must be retried exactly once"

    def test_no_second_retry_after_first_retry_fails(self):
        """Only one retry allowed — terminal error after two nmcli failures."""
        patches = _base_patches()
        patches['wifi.connect'] = MagicMock(
            side_effect=subprocess.CalledProcessError(1, 'nmcli')
        )
        with _apply_patches(patches):
            provision.run()

        assert patches['wifi.connect'].call_count == 2, \
            "connect must be called exactly twice (first attempt + one retry)"
        # After two failures, run() exits — no infinite loop
        assert patches['server.create_server'].call_count == 2


# ---------------------------------------------------------------------------
# swtpm unexpected exit → terminal ERROR
# ---------------------------------------------------------------------------

class TestSwtpmDies:
    def test_terminal_error_if_swtpm_dies(self):
        """swtpm dying mid-session must cause terminal ERROR — no retry."""
        patches = _base_patches(swtpm_alive=False)  # swtpm reported dead
        with _apply_patches(patches):
            provision.run()

        # connect must never be called — terminal error before PROVISIONED
        patches['wifi.connect'].assert_not_called()
        # create_server called once (for the first AP_MODE entry) then terminal exit
        assert patches['server.create_server'].call_count == 1
