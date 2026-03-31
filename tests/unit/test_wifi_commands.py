"""
Unit tests for wifi.py — subprocess argument construction.

All subprocess calls are mocked. No real processes are started.
Mock targets use the usage-module pattern: patch('wifi.subprocess.*').
"""

import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import wifi


@pytest.fixture(autouse=True)
def reset_wifi_state():
    """Reset wifi module globals between tests so they don't bleed across."""
    yield
    wifi._hostapd_proc = None
    wifi._dnsmasq_proc = None
    wifi._hostapd_conf_path = None
    wifi._dnsmasq_conf_path = None


# ---------------------------------------------------------------------------
# start_ap
# ---------------------------------------------------------------------------

class TestStartAp:
    def test_calls_hostapd(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            assert any(cmd[0] == 'hostapd' for cmd in commands), \
                "hostapd was not invoked"

    def test_calls_dnsmasq(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            assert any(cmd[0] == 'dnsmasq' for cmd in commands), \
                "dnsmasq was not invoked"

    def test_hostapd_receives_conf_file(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            hostapd_cmd = next(c for c in commands if c[0] == 'hostapd')
            # Second argument must be a file path (not empty, not the binary name)
            assert len(hostapd_cmd) >= 2
            assert hostapd_cmd[1].endswith('.conf')

    def test_dnsmasq_receives_conf_file(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            dnsmasq_cmd = next(c for c in commands if c[0] == 'dnsmasq')
            conf_args = [a for a in dnsmasq_cmd if a.endswith('.conf')]
            assert conf_args, "dnsmasq not called with a .conf file path"

    def test_interface_substituted_in_hostapd_conf(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan1')

            # The conf file is written to disk even though Popen is mocked
            conf_path = wifi._hostapd_conf_path
            assert conf_path is not None
            content = Path(conf_path).read_text()
            assert 'wlan1' in content, \
                f"PROVISION_IFACE 'wlan1' not found in hostapd.conf:\n{content}"

    def test_interface_substituted_in_dnsmasq_conf(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan1')

            conf_path = wifi._dnsmasq_conf_path
            assert conf_path is not None
            content = Path(conf_path).read_text()
            assert 'wlan1' in content, \
                f"PROVISION_IFACE 'wlan1' not found in dnsmasq.conf:\n{content}"


# ---------------------------------------------------------------------------
# stop_ap
# ---------------------------------------------------------------------------

class TestStopAp:
    def test_terminates_hostapd_process(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            wifi.start_ap('wlan0')

        wifi.stop_ap()
        mock_proc.terminate.assert_called()

    def test_terminates_dnsmasq_process(self):
        with patch('wifi.subprocess.Popen') as mock_popen:
            procs = [MagicMock(), MagicMock()]
            mock_popen.side_effect = procs
            wifi.start_ap('wlan0')

        wifi.stop_ap()
        # Both procs should have been terminated
        for proc in procs:
            proc.terminate.assert_called()

    def test_safe_to_call_without_start(self):
        """stop_ap with no running processes must not raise."""
        wifi.stop_ap()  # should not raise


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

class TestConnect:
    def test_nmcli_receives_correct_args(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run') as mock_run:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')
            wifi.connect('MyNet', 'secret')

        mock_run.assert_called_once_with(
            ['nmcli', 'device', 'wifi', 'connect', 'MyNet', 'password', 'secret'],
            check=True,
        )

    def test_args_are_list_not_shell_string(self):
        """Credentials must be passed as discrete list args (no shell=True)."""
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run') as mock_run:
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')
            wifi.connect('Net with spaces', 'p@$$w0rd!')

        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert isinstance(cmd, list), "nmcli must be called with a list, not a shell string"
        assert 'Net with spaces' in cmd
        assert 'p@$$w0rd!' in cmd
        assert kwargs.get('shell', False) is False

    def test_calls_stop_ap_before_nmcli(self):
        """AP must be torn down before nmcli connect (required on Raspberry Pi BCM43xx)."""
        call_order = []

        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run') as mock_run:
            mock_proc = MagicMock()
            mock_proc.terminate.side_effect = lambda: call_order.append('terminate')
            mock_run.side_effect = lambda *a, **kw: call_order.append('nmcli')
            mock_popen.return_value = mock_proc

            wifi.start_ap('wlan0')
            wifi.connect('Net', 'pw')

        assert call_order.index('terminate') < call_order.index('nmcli'), \
            "stop_ap (terminate) must be called before nmcli connect"
