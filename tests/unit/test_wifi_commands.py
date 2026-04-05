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


# ---------------------------------------------------------------------------
# start_ap
# ---------------------------------------------------------------------------

class TestStartAp:
    def test_calls_hostapd(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            assert any(cmd[0] == 'hostapd' for cmd in commands), \
                "hostapd was not invoked"

    def test_calls_dnsmasq(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            assert any(cmd[0] == 'dnsmasq' for cmd in commands), \
                "dnsmasq was not invoked"

    def test_hostapd_receives_conf_file(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            hostapd_cmd = next(c for c in commands if c[0] == 'hostapd')
            assert len(hostapd_cmd) >= 2
            assert hostapd_cmd[1].endswith('.conf')

    def test_dnsmasq_receives_interface_arg(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            dnsmasq_cmd = next(c for c in commands if c[0] == 'dnsmasq')
            assert any('--interface=wlan0' in a for a in dnsmasq_cmd), \
                "dnsmasq not called with --interface=wlan0"

    def test_interface_substituted_in_hostapd_conf(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan1')

            conf_path = wifi._hostapd_conf_path
            assert conf_path is not None
            content = Path(conf_path).read_text()
            assert 'wlan1' in content, \
                f"PROVISION_IFACE 'wlan1' not found in hostapd.conf:\n{content}"

    def test_interface_substituted_in_dnsmasq_args(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan1')

            commands = [c[0][0] for c in mock_popen.call_args_list]
            dnsmasq_cmd = next(c for c in commands if c[0] == 'dnsmasq')
            assert any('wlan1' in a for a in dnsmasq_cmd), \
                f"PROVISION_IFACE 'wlan1' not found in dnsmasq args: {dnsmasq_cmd}"


# ---------------------------------------------------------------------------
# stop_ap
# ---------------------------------------------------------------------------

class TestStopAp:
    def test_terminates_hostapd_process(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc
            wifi.start_ap('wlan0')

        wifi.stop_ap()
        mock_proc.terminate.assert_called()

    def test_terminates_dnsmasq_process(self):
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run'), \
             patch('wifi.time.sleep'):
            procs = [MagicMock(), MagicMock()]
            mock_popen.side_effect = procs
            wifi.start_ap('wlan0')

        wifi.stop_ap()
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
             patch('wifi.subprocess.run') as mock_run, \
             patch('wifi.time.sleep'):
            mock_run.return_value = MagicMock(returncode=0)
            mock_popen.return_value = MagicMock()
            wifi.start_ap('wlan0')
            wifi.connect('MyNet', 'secret')

        mock_run.assert_called_with(
            ['nmcli', 'device', 'wifi', 'connect', 'MyNet', 'password', 'secret'],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_args_are_list_not_shell_string(self):
        """Credentials must be passed as discrete list args (no shell=True)."""
        with patch('wifi.subprocess.Popen') as mock_popen, \
             patch('wifi.subprocess.run') as mock_run, \
             patch('wifi.time.sleep'):
            mock_run.return_value = MagicMock(returncode=0)
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
             patch('wifi.subprocess.run') as mock_run, \
             patch('wifi.time.sleep'):
            mock_proc = MagicMock()
            mock_proc.terminate.side_effect = lambda: call_order.append('terminate')

            def track_run(cmd, **kw):
                m = MagicMock()
                m.returncode = 0
                if cmd[0] == 'nmcli':
                    call_order.append('nmcli')
                return m

            mock_run.side_effect = track_run
            mock_popen.return_value = mock_proc

            wifi.start_ap('wlan0')
            wifi.connect('Net', 'pw')

        assert call_order.index('terminate') < call_order.index('nmcli'), \
            "stop_ap (terminate) must be called before nmcli connect"


# ---------------------------------------------------------------------------
# WifiConnectError — failure reason parsing
# ---------------------------------------------------------------------------

class TestWifiConnectError:
    def _run_mock(self, returncode, stderr=''):
        m = MagicMock()
        m.returncode = returncode
        m.stderr = stderr
        return m

    def test_raises_on_nonzero_exit(self):
        with patch('wifi.subprocess.Popen'), patch('wifi.time.sleep'), \
             patch('wifi.subprocess.run', return_value=self._run_mock(4, 'Secrets were required')):
            wifi.start_ap('wlan0')
            with pytest.raises(wifi.WifiConnectError):
                wifi.connect('Net', 'wrongpw')

    def test_no_error_on_success(self):
        with patch('wifi.subprocess.Popen'), patch('wifi.time.sleep'), \
             patch('wifi.subprocess.run', return_value=self._run_mock(0, '')):
            wifi.start_ap('wlan0')
            wifi.connect('Net', 'pw')  # must not raise

    def test_wrong_password_user_message(self):
        with patch('wifi.subprocess.Popen'), patch('wifi.time.sleep'), \
             patch('wifi.subprocess.run',
                   return_value=self._run_mock(4, 'Secrets were required, but not provided')):
            wifi.start_ap('wlan0')
            with pytest.raises(wifi.WifiConnectError) as exc_info:
                wifi.connect('Net', 'wrongpw')
        assert 'password' in exc_info.value.user_message.lower()

    def test_ssid_not_found_user_message(self):
        with patch('wifi.subprocess.Popen'), patch('wifi.time.sleep'), \
             patch('wifi.subprocess.run',
                   return_value=self._run_mock(10, "No network with SSID 'GhostNet' found")):
            wifi.start_ap('wlan0')
            with pytest.raises(wifi.WifiConnectError) as exc_info:
                wifi.connect('GhostNet', 'pw')
        assert 'GhostNet' in exc_info.value.user_message
        assert 'not found' in exc_info.value.user_message.lower()

    def test_fallback_user_message(self):
        with patch('wifi.subprocess.Popen'), patch('wifi.time.sleep'), \
             patch('wifi.subprocess.run',
                   return_value=self._run_mock(1, 'Some other error')):
            wifi.start_ap('wlan0')
            with pytest.raises(wifi.WifiConnectError) as exc_info:
                wifi.connect('SomeNet', 'pw')
        assert 'SomeNet' in exc_info.value.user_message
