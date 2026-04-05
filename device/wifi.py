"""
wifi.py — SoftAP lifecycle and nmcli station connect.

Owns the full SoftAP lifecycle:
  - Writes hostapd.conf to a temp file and starts hostapd.
  - Assigns the gateway IP (192.168.4.1) to the interface.
  - Starts dnsmasq via command-line arguments (no conf file).
  - Issues the final nmcli station connect.

provision.py calls start_ap(iface) only — no config file paths cross
the module boundary.
"""

import subprocess
import tempfile
import time


class WifiConnectError(Exception):
    """Raised when nmcli fails to connect to the target network."""
    def __init__(self, message: str, user_message: str):
        super().__init__(message)
        self.user_message = user_message

# ---------------------------------------------------------------------------
# Config templates
# ---------------------------------------------------------------------------

_HOSTAPD_CONF = """\
interface={iface}
driver=nl80211
ssid=Wajntraub-Demo-{suffix}
hw_mode=g
channel=6
auth_algs=1
ignore_broadcast_ssid=0
"""


def _get_mac_suffix(iface: str) -> str:
    """Return the last 3 octets of the interface MAC as 6 uppercase hex chars.

    Reads /sys/class/net/<iface>/address. Falls back to '000000' on error.
    """
    try:
        with open(f'/sys/class/net/{iface}/address') as f:
            mac = f.readline().strip()
        return mac.replace(':', '')[-6:].upper()
    except OSError:
        return '000000'

_DNSMASQ_BASE_ARGS = [
    'dnsmasq', '--no-daemon',
    '--bind-interfaces',
    '--dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h',
    '--address=/setup.wajntraub-demo.local/192.168.4.1',
]

# ---------------------------------------------------------------------------
# Module state — one AP session at a time
# ---------------------------------------------------------------------------

_hostapd_proc = None
_dnsmasq_proc = None
_hostapd_conf_path = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_ap(iface: str) -> None:
    """
    Start hostapd and dnsmasq for *iface*, assigning 192.168.4.1 as gateway.

    The hostapd config is written to a temp file. dnsmasq is started with
    command-line arguments directly to avoid conf-file parsing issues with
    systemd-resolved holding port 53.
    """
    global _hostapd_proc, _dnsmasq_proc, _hostapd_conf_path

    # Clean up any leftover state from a previous crashed run
    subprocess.run(['pkill', '-f', 'hostapd'], check=False)
    subprocess.run(['pkill', '-f', 'dnsmasq'], check=False)
    subprocess.run(['ip', 'addr', 'del', '192.168.4.1/24', 'dev', iface], check=False)
    time.sleep(0.3)

    # Write hostapd config
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.conf', prefix='wajntraub-hostapd-', delete=False
    ) as f:
        f.write(_HOSTAPD_CONF.format(iface=iface, suffix=_get_mac_suffix(iface)))
        _hostapd_conf_path = f.name

    _hostapd_proc = subprocess.Popen(['hostapd', _hostapd_conf_path])
    # Wait briefly for hostapd to bring the interface up, then assign the
    # gateway IP before starting dnsmasq
    time.sleep(1)
    subprocess.run(
        ['ip', 'addr', 'add', '192.168.4.1/24', 'dev', iface],
        check=False,  # ignore error if already assigned
    )
    _dnsmasq_proc = subprocess.Popen(
        _DNSMASQ_BASE_ARGS + [f'--interface={iface}']
    )


def stop_ap() -> None:
    """Terminate hostapd and dnsmasq, and remove the gateway IP from the interface."""
    global _hostapd_proc, _dnsmasq_proc

    if _hostapd_proc is not None:
        _hostapd_proc.terminate()
        _hostapd_proc = None

    if _dnsmasq_proc is not None:
        _dnsmasq_proc.terminate()
        _dnsmasq_proc = None

    if _hostapd_conf_path is not None:
        # Derive interface from the conf file and remove the gateway IP
        try:
            conf = open(_hostapd_conf_path).read()
            for line in conf.splitlines():
                if line.startswith('interface='):
                    iface = line.split('=', 1)[1].strip()
                    subprocess.run(
                        ['ip', 'addr', 'del', '192.168.4.1/24', 'dev', iface],
                        check=False,
                    )
                    break
        except OSError:
            pass


def connect(ssid: str, password: str) -> None:
    """
    Tear down the SoftAP and connect to the target Wi-Fi network.

    Credentials are passed as discrete list arguments to nmcli — never
    interpolated into a shell string — to prevent shell injection.

    Raises WifiConnectError on failure with a user-facing message that
    distinguishes wrong password from SSID not found from other errors.
    """
    stop_ap()
    result = subprocess.run(
        ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr
        if 'Secrets were required' in stderr or result.returncode == 4:
            user_message = 'Incorrect Wi-Fi password — please check and try again.'
        elif f"No network with SSID '{ssid}'" in stderr or result.returncode == 10:
            user_message = f"Network '{ssid}' not found — check the network name and try again."
        else:
            user_message = f"Could not connect to '{ssid}' — please try again."
        raise WifiConnectError(
            f"nmcli failed (exit {result.returncode}): {stderr.strip()}",
            user_message=user_message,
        )
