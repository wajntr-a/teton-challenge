# teton-challenge — Implementation Plan

## 1. Implementation Strategy

Build bottom-up along the dependency graph: scaffold first, then the two leaf modules (`wifi.py`, `server.py`) with their unit tests, then the orchestrator (`provision.py`) that imports both, then integration tests that require a live swtpm. Scripts (`setup.sh`, `install-ca.sh`) have no Python dependencies and can be written in parallel with the Python modules.

The guiding constraint is that nothing can be integration-tested until `setup.sh` produces a valid cert chain and swtpm handle. Unit tests are written alongside each module so the test suite grows incrementally and failures are local to the module under development.

## 2. Milestones

### Milestone 1: Runnable scaffold

**Goal**: Repo structure is in place, `setup.sh` produces a valid swtpm state and cert chain, `install-ca.sh` installs the CA on Ubuntu, test fixtures are ready.

**Tasks**:
- `scaffold` — Create `device/`, `scripts/`, `tests/unit/`, `tests/integration/`, `requirements.txt` (flask), `requirements-test.txt` (pytest, requests), `.gitignore` (certs/, __pycache__, *.pyc, /tmp/tpm-*)
- `setup-sh` — Write `scripts/setup.sh`: start swtpm, create Teton demo CA with OpenSSL CLI, generate RSA key in TPM at handle `0x81000001`, create device CSR from TPM public key, sign CSR → `certs/device.crt`; output `certs/teton-ca.crt`; idempotent (wipe swtpm state before each run)
- `install-ca-sh` — Write `scripts/install-ca.sh`: copy `certs/teton-ca.crt` to `/usr/local/share/ca-certificates/`, run `update-ca-certificates`; detect Firefox profile at `~/.mozilla/firefox/*.default-release/` and run `certutil -A`; require `libnss3-tools`; idempotent
- `test-conftest-root` — Write `tests/conftest.py`: insert `device/` into `sys.path`; provide `tmp_cert_dir` fixture (pytest.tmp_path scoped); provide `generate_test_ca` and `generate_test_device_cert` helper fixtures using OpenSSL CLI
- `test-conftest-integration` — Write `tests/integration/conftest.py`: self-contained swtpm lifecycle fixture — start swtpm with socket and state in `pytest.tmp_path`, set `TPM2TOOLS_TCTI` and `TSS2_TCTI` env vars scoped to test process, generate test CA + device cert in `pytest.tmp_path`, yield fixture dict, stop swtpm on teardown

### Milestone 2: SoftAP module + credential server

**Goal**: `wifi.py` can start and stop the SoftAP, `server.py` serves the credential form over real TLS; unit tests for both pass.

**Tasks**:
- `wifi-py` — Write `device/wifi.py`: render `hostapd.conf` inline template to `tempfile.NamedTemporaryFile` (substituting `PROVISION_IFACE`); render `dnsmasq.conf` inline template similarly; expose `start_ap(iface)` (writes configs, starts hostapd and dnsmasq via subprocess), `stop_ap()` (kills both processes), `connect(ssid, password)` (tears down AP, issues `nmcli device wifi connect`)
- `server-py` — Write `device/server.py`: expose `create_server(credentials, event, ssl_context)` — creates Flask app, binds via `werkzeug.serving.make_server()` with provided `ssl_context`, starts daemon thread, returns `(server_instance, thread)`; `GET /` returns inline HTML credential form; `POST /provision` validates non-empty ssid + password, stores in `credentials` dict, sets `event`, calls `server_instance.shutdown()`, returns inline HTML success page; error responses inject `error_reason` via f-string; all responses include `Strict-Transport-Security: max-age=31536000`
- `test-validation` — Write `tests/unit/test_validation.py`: test `POST /provision` with valid input, empty ssid, empty password, missing fields — import `server` module directly, call handler logic
- `test-wifi-commands` — Write `tests/unit/test_wifi_commands.py`: test `start_ap`, `stop_ap`, `connect` — mock `wifi.subprocess.run` and `wifi.subprocess.Popen`; assert correct command arguments are constructed; assert temp config files contain expected interface substitutions

### Milestone 3: Orchestrator + integration tests

**Goal**: `provision.py` runs the full state machine; all unit and integration tests pass.

**Tasks**:
- `provision-py` — Write `device/provision.py`: implement `ProvisionState` enum; construct `ssl.SSLContext` once in `INIT` (load TPM key via `tpm2-openssl` provider at handle `0x81000001`); call `wifi.start_ap(iface)` and `server.create_server(credentials, event, ssl_context)` on each `AP_MODE` entry; block on `event.wait(timeout=600)`; on timeout → `ERROR`; on event → join server thread → call `wifi.connect(ssid, password)` → `CONNECTING`; on nmcli success → `ONLINE`; on nmcli failure → `ERROR → AP_MODE` (one retry, reuse ssl_context); log every state transition at INFO; guard runnable block with `if __name__ == "__main__"`
- `test-state-machine` — Write `tests/unit/test_state_machine.py`: mock `provision.ssl.SSLContext`, `wifi.start_ap`, `wifi.stop_ap`, `wifi.connect`, `server.create_server`; test each state transition: INIT→AP_MODE, AP_MODE→PROVISIONED (event set), PROVISIONED→CONNECTING, CONNECTING→ONLINE, CONNECTING→ERROR, ERROR→AP_MODE retry, AP_MODE→ERROR (timeout), swtpm unexpected exit → terminal ERROR
- `test-server-integration` — Write `tests/integration/test_server.py`: using the swtpm fixture from `integration/conftest.py`, construct real `ssl.SSLContext` from test TPM handle, call `create_server()`, issue `requests.get('https://setup.teton-device.local/', verify=test_ca_path)` and `requests.post(..., data={ssid, password})` against `127.0.0.1:443`; assert credentials land in shared dict and event is set; assert HSTS header present; assert empty-field POST returns error response

### Milestone 4: Demo verification

**Goal**: Full provisioning flow runs on target machine; submission evidence collected.

**Tasks**:
- `demo-run` — Run `sudo ./scripts/setup.sh`, `sudo ./scripts/install-ca.sh`, `sudo python3 device/provision.py`; connect to `Teton-Device-XXXX` AP; navigate to `https://setup.teton-device.local`; submit credentials; verify device connects to target network (`ip addr`, `ping`)
- `submission-evidence` — Capture terminal log output, browser screenshots (form, success page), `ip addr` output, `ping` output; add to README

## 3. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `tpm2-openssl` provider fails to load in `ssl.SSLContext` on target OS | High | Test `setup.sh` + SSLContext construction in isolation before writing provision.py; verify `openssl list -providers` shows tpm2 provider |
| `hostapd`/`dnsmasq` subprocess calls fail due to missing root or interface name | High | Test `wifi.start_ap()` manually on target hardware early in M2; use `PROVISION_IFACE` env var to override default `wlan0` |
| Raspberry Pi BCM43xx AP+station sequencing — `nmcli connect` fails if AP not fully torn down | Med | Call `wifi.stop_ap()` and add brief settle delay before `nmcli connect`; verify on Pi hardware before M3 integration tests |
| `werkzeug_server.shutdown()` does not unblock cleanly on Python 3.11+ | Med | Test shutdown + thread join manually in M2 before wiring into provision.py; fall back to `server._BaseServer.shutdown()` if needed |
| swtpm handle `0x81000001` conflicts with system TPM on evaluation machine | Low | swtpm uses isolated socket `/tmp/tpm.sock`; `TPM2TOOLS_TCTI` env var routes all `tpm2-tools` calls to swtpm — system TPM never accessed |
