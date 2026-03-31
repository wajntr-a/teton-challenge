"""
wifi.py — SoftAP lifecycle and nmcli station connect.

Owns the full SoftAP lifecycle:
  - Renders hostapd.conf and dnsmasq.conf inline templates to temp files
    (substituting PROVISION_IFACE).
  - Starts and stops hostapd and dnsmasq daemons.
  - Issues the final nmcli station connect.

provision.py calls start_ap(iface) only — no config file paths cross
the module boundary.
"""

import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Config templates
# ---------------------------------------------------------------------------

_HOSTAPD_CONF = """\
interface={iface}
driver=nl80211
ssid=Teton-Device-0000
hw_mode=g
channel=6
auth_algs=1
ignore_broadcast_ssid=0
"""

_DNSMASQ_CONF = """\
interface={iface}
bind-interfaces
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/setup.teton-device.local/192.168.4.1
"""

# ---------------------------------------------------------------------------
# Module state — one AP session at a time
# ---------------------------------------------------------------------------

_hostapd_proc = None
_dnsmasq_proc = None
_hostapd_conf_path = None
_dnsmasq_conf_path = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_ap(iface: str) -> None:
    """
    Write hostapd and dnsmasq configs for *iface* and start both daemons.

    Config files are written to temporary files in /tmp. The file paths are
    stored in module globals (_hostapd_conf_path, _dnsmasq_conf_path) for
    inspection by tests.
    """
    global _hostapd_proc, _dnsmasq_proc, _hostapd_conf_path, _dnsmasq_conf_path

    # Write hostapd config
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.conf', prefix='teton-hostapd-', delete=False
    ) as f:
        f.write(_HOSTAPD_CONF.format(iface=iface))
        _hostapd_conf_path = f.name

    # Write dnsmasq config
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.conf', prefix='teton-dnsmasq-', delete=False
    ) as f:
        f.write(_DNSMASQ_CONF.format(iface=iface))
        _dnsmasq_conf_path = f.name

    _hostapd_proc = subprocess.Popen(['hostapd', _hostapd_conf_path])
    _dnsmasq_proc = subprocess.Popen(
        ['dnsmasq', '--no-daemon', '--conf-file', _dnsmasq_conf_path]
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
