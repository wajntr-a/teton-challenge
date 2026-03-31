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

# ---------------------------------------------------------------------------
# Config templates
# ---------------------------------------------------------------------------

_HOSTAPD_CONF = """\
interface={iface}
driver=nl80211
ssid=Wajntraub-Demo-0000
hw_mode=g
channel=6
auth_algs=1
ignore_broadcast_ssid=0
"""

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

    # Write hostapd config
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.conf', prefix='wajntraub-hostapd-', delete=False
    ) as f:
        f.write(_HOSTAPD_CONF.format(iface=iface))
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
    """Terminate hostapd and dnsmasq if running."""
    global _hostapd_proc, _dnsmasq_proc

    if _hostapd_proc is not None:
        _hostapd_proc.terminate()
        _hostapd_proc = None

    if _dnsmasq_proc is not None:
        _dnsmasq_proc.terminate()
        _dnsmasq_proc = None


def connect(ssid: str, password: str) -> None:
    """
    Tear down the SoftAP and connect to the target Wi-Fi network.

    Credentials are passed as discrete list arguments to nmcli — never
    interpolated into a shell string — to prevent shell injection.
    """
    stop_ap()
    subprocess.run(
        ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
        check=True,
    )
