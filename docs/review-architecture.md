## Review — 2026-03-30 00:03

```
INDEPENDENT REVIEW — teton-challenge / architecture phase
Mode: forward-only
Reviewer: fresh agent (no project context)
Date: 2026-03-30

--- FORWARD REVIEW (principal engineer perspective) ---

[PASS] Component boundaries — all components are server-side; no ambiguity
[PASS] DOM access pattern — not applicable; plain HTML form, no JS
[PASS] JS-toggled CSS classes — not applicable
[PASS] Observer configuration — not applicable
[NOTE] Test infrastructure — subprocess mock target path unspecified
  Question: Unit tests for wifi.py will mock subprocess calls. The architecture does not
  specify whether the patch target is wifi.subprocess.run or subprocess.run. The distinction
  affects whether the mock actually intercepts the call. Not a structural blocker, but one
  line would prevent a common first-attempt error.
[PASS] E2E target — E2E explicitly out of scope; no gap
[NOTE] File tree completeness — ProvisionState location unspecified
  Question: test_state_machine.py needs to import the state machine enum and transition
  logic. The architecture assigns orchestration to provision.py, but does not say whether
  the state enum lives in provision.py (importable only if guarded by if __name__ == "__main__")
  or in a separate importable module (e.g., state.py). This affects the file tree.
[PASS] Deferred items — Section 12 thorough and correctly scoped
[GAP] provision.py / wifi.py interface — config file handoff undefined
  Question: provision.py writes hostapd/dnsmasq config to temp files "from an inline
  template." wifi.py owns the "SoftAP bring-up/tear-down sequence." The architecture does
  not define the calling contract: does wifi.py receive the temp file paths as arguments,
  construct them itself, or read from a shared location? This is a cross-component data
  flow decision that affects both files' interfaces and cannot easily be changed once both
  are written.
[GAP] Retry path — swtpm state and SSLContext reuse on ERROR → AP_MODE unspecified
  Question: ssl.SSLContext is constructed once during INIT. On ERROR → AP_MODE retry,
  the architecture does not specify whether the swtpm process is restarted or whether the
  pre-built SSLContext is reused. If swtpm crashes or needs restart on the retry path,
  the INIT-constructed SSLContext would be invalid. This edge-case data flow through the
  swtpm → SSLContext → retry AP_MODE boundary must be resolved before the implementation
  plan is written.

--- RESULT: BLOCK ---
  Blockers: 2 forward gap(s)
  Advisory: 2 note(s)
```

---

## Review — 2026-03-30 00:02

```
INDEPENDENT REVIEW — teton-challenge / architecture phase
Mode: forward-only
Reviewer: fresh agent (no project context)
Date: 2026-03-30

--- FORWARD REVIEW (principal engineer perspective) ---

[PASS] Component boundaries — all components server-side; no ambiguity
[PASS] DOM access pattern — not applicable; plain HTML form, no JS
[PASS] JS-toggled CSS classes — not applicable
[PASS] Observer configuration — not applicable
[NOTE] Test infrastructure — conftest.py dependency direction unspecified
  Question: Integration tests need both a running swtpm AND a cert chain signed by that
  swtpm's TPM key. The architecture separates cert generation helpers (root conftest.py)
  from the swtpm lifecycle fixture (integration/conftest.py). Which calls which? Does
  integration/conftest.py call up to the parent fixture, or is it self-contained?
  Wrong direction causes awkward restructuring once both conftest files exist.
[PASS] E2E target — explicitly stated out of scope
[NOTE] File tree completeness — HTML template file location unspecified
  Question: Are HTML responses (credential form, success page, error page) inline strings
  in server.py or Jinja2 templates in device/templates/? This is a structural file-tree
  decision: different implications for how server.py is tested and structured.
[PASS] Deferred items — Section 12 thorough and correctly scoped
[GAP] Open catch-all — ssl.SSLContext ownership on retry path unresolved
  Question: On ERROR → AP_MODE retry, provision.py calls create_server() again.
  If ssl.SSLContext (TPM key load via tpm2-openssl) is constructed inside create_server(),
  it loads the TPM key twice and must succeed on second call with same swtpm state.
  If constructed once in INIT and passed into create_server(), the function signature
  and ownership boundary between provision.py and server.py changes.
  This is a component interface decision at the provision.py/server.py boundary —
  not a standard pattern, specific to this TPM integration — and cannot be guessed.

--- RESULT: BLOCK ---
  Blockers: 1 forward gap(s)
  Advisory: 2 note(s)
```

---

## Review — 2026-03-30 00:01

```
INDEPENDENT REVIEW — teton-challenge / architecture phase
Mode: forward-only
Reviewer: fresh agent (no project context)
Date: 2026-03-30

--- FORWARD REVIEW (principal engineer perspective) ---

[PASS] Component boundaries — all components server-side; no ambiguity
[PASS] DOM access pattern — not applicable; plain HTML form, no JS
[PASS] JS-toggled CSS classes — not applicable
[PASS] Observer configuration — not applicable
[NOTE] Test infrastructure — conftest.py ownership ambiguous
  Question: Root tests/conftest.py and tests/integration/conftest.py both claim swtpm
  lifecycle fixtures. Which is authoritative? Does root conftest provide a shared swtpm
  for all tests, or only non-swtpm shared fixtures? A wrong reading causes either
  double-spawning or accidental scope sharing between unit and integration.
[NOTE] E2E target — E2E out-of-scope not explicitly stated
  Question: One sentence confirming "E2E testing is out of scope for this submission"
  would prevent an implementer from wondering whether a Playwright test was expected.
[GAP] File tree completeness — install-ca.sh and HTML template model unspecified
  Question 1: install-ca.sh has no component description — what OS paths does it
  touch, what are its governing constraints? "Platform detection logic TBD" in
  Section 12 is not a substitute for an architectural boundary.
  Question 2: Are HTML responses inline strings in server.py, or Jinja2 templates
  in a device/templates/ directory? This is a structural file-tree decision with
  downstream consequences for test strategy and cannot easily be changed after
  tickets are written.
[PASS] Deferred items — Section 12 is thorough and internally consistent
[GAP] Open catch-all — Flask server restart on ERROR → AP_MODE retry undefined
  Question: When CONNECTING → ERROR → AP_MODE fires, provision.py must restart the
  Flask server thread. The architecture does not specify how: is a new
  werkzeug.serving.make_server() instance constructed? Is there a factory function?
  This threading coordination pattern affects both provision.py and server.py's
  structure and cannot be changed after those files exist.

--- RESULT: BLOCK ---
  Blockers: 2 forward gap(s)
  Advisory: 2 note(s)
```

---

## Review — 2026-03-30 00:00

```
INDEPENDENT REVIEW — teton-challenge / architecture phase
Mode: both
Reviewer: fresh agent (no project context)
Date: 2026-03-30

--- CHECKLIST RESULTS ---

[PASS] All phase artifacts exist and are complete (no empty placeholder sections)
[PASS] Git commit(s) for the phase work exist on the phase branch
[PASS] docs/architecture.md exists and follows the template
[PASS] C4 diagrams are present and accurate
[PASS] Technology stack is justified
[PASS] Every component has an explicit type (server/client) and governing ADs listed
[WARN] Data model covers all spec requirements
  Missing: Credential flow between server.py and wifi.py is implicit, not stated. Error state
  data (what is captured, what is shown) is undefined.
  Fix: Add a "Credential Flow" and "Error State" subsection to Section 5 explicitly stating
  that credentials are passed to wifi.py.connect(ssid, password) then discarded, and that
  error_reason string drives the error page shown to the user.
[PASS] Test strategy defines levels, tools, and coverage targets
[PASS] Deployment approach is defined
[PASS] Items deferred to tickets are listed in Section 12

--- FORWARD REVIEW (principal engineer perspective) ---

[PASS] Component boundaries — all components are server-side; no ambiguity
[PASS] DOM access pattern — not applicable; plain HTML form, no JS
[PASS] JS-toggled CSS classes — not applicable
[PASS] Observer configuration — not applicable
[NOTE] Test infrastructure — integration TLS fixture wiring unspecified
  Question: Does the swtpm pytest fixture pass verify=path/to/test-ca.crt to requests, or
  does it patch the system trust store? The architecture says "requests with custom CA" but
  does not resolve this. A misread produces a non-obvious SSL verification failure.
[PASS] E2E target — no E2E tier; explicitly scoped out; no gap
[GAP] File tree completeness — hostapd.conf and dnsmasq.conf lifecycle unresolved
  Question: Are device/hostapd.conf and device/dnsmasq.conf static files committed to the
  repo, or generated by setup.sh (or by provision.py at runtime via env var substitution)?
  This determines the repo structure and the setup.sh contract — both hard to change after
  tickets are written.
[NOTE] Deferred items — systemd deferred in §11 but absent from §12
  Question: Should a systemd unit file ticket be added to Section 12 so it flows into the
  ticket list? Currently it will not be picked up by the ticketing phase.
[GAP] Open catch-all — Flask shutdown / server→orchestrator IPC unresolved
  Question: Flask 3.x removed werkzeug.server.shutdown. How does server.py signal
  provision.py that credentials have been received? The architecture says credentials are
  "returned to orchestrator" and the server "shuts down after successful POST" but does not
  specify the IPC mechanism (shared threading.Event, queue, os.kill, etc.). This is the
  interface boundary between server.py and provision.py — must be decided before tickets
  are scoped.

--- RESULT: BLOCK ---
  Blockers: 0 checklist fail(s), 2 forward gap(s)
  Advisory: 1 warn(s), 2 note(s)
```
