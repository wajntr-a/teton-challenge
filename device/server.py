"""
server.py — Flask HTTPS credential server.

create_app()   — Creates the Flask app. Accepts a shutdown_callback so the
                 POST handler can signal server shutdown without a circular
                 dependency. Used directly by unit tests via test_client().

create_server() — Binds the app to a werkzeug HTTPS server on port 443 in a
                  daemon thread. Returns (server_instance, thread) so that
                  provision.py can join the thread after the event fires and
                  call create_server() again on retry without port 443 conflicts.
"""

import threading

from flask import Flask, make_response, request
from werkzeug.serving import make_server

# ---------------------------------------------------------------------------
# Inline HTML responses — no template engine, no templates/ directory
# ---------------------------------------------------------------------------

_CSS = """\
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0a0a0a;
    color: #e8e8e8;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }

  .card {
    background: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 2.5rem 2rem;
    width: 100%;
    max-width: 400px;
  }

  .logo {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 2rem;
  }

  h1 {
    font-size: 1.35rem;
    font-weight: 600;
    color: #f0f0f0;
    margin-bottom: 0.5rem;
  }

  .subtitle {
    font-size: 0.875rem;
    color: #666;
    margin-bottom: 2rem;
    line-height: 1.5;
  }

  .field {
    margin-bottom: 1.25rem;
  }

  label {
    display: block;
    font-size: 0.8rem;
    font-weight: 500;
    color: #999;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 0.4rem;
  }

  input {
    width: 100%;
    padding: 0.65rem 0.9rem;
    background: #1e1e1e;
    border: 1px solid #2e2e2e;
    border-radius: 6px;
    color: #f0f0f0;
    font-size: 1rem;
    outline: none;
    transition: border-color 0.15s;
  }

  input:focus {
    border-color: #4a90d9;
  }

  button {
    width: 100%;
    padding: 0.75rem;
    margin-top: 0.5rem;
    background: #4a90d9;
    color: #fff;
    font-size: 0.95rem;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s;
  }

  button:hover { background: #3a7fc8; }
  button:active { background: #2d6db5; }

  .message {
    font-size: 0.9rem;
    color: #aaa;
    line-height: 1.6;
    margin-top: 1rem;
  }

  .error-text { color: #e05c5c; }

  a { color: #4a90d9; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
"""

_FORM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Device Setup</title>""" + _CSS + """</head>
<body>
  <div class="card">
    <div class="logo">Device Setup</div>
    <h1>Connect to Wi-Fi</h1>
    <p class="subtitle">Enter the credentials for the network this device should join.</p>
    <form method="POST" action="/provision">
      <div class="field">
        <label for="ssid">Network name (SSID)</label>
        <input id="ssid" type="text" name="ssid" required autofocus autocomplete="off" spellcheck="false">
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input id="password" type="password" name="password" required autocomplete="off">
      </div>
      <button type="submit">Provision device</button>
    </form>
  </div>
</body>
</html>
"""

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Provisioning complete</title>""" + _CSS + """</head>
<body>
  <div class="card">
    <div class="logo">Device Setup</div>
    <h1>Provisioning complete</h1>
    <p class="message">The device is connecting to your network. You may close this page.</p>
  </div>
</body>
</html>
"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Provisioning error</title>""" + _CSS + """</head>
<body>
  <div class="card">
    <div class="logo">Device Setup</div>
    <h1>Something went wrong</h1>
    <p class="message error-text">{error_reason}</p>
    <p class="message"><a href="/">Try again</a></p>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(credentials: dict, event: threading.Event, shutdown_callback=None):
    """
    Create and return the Flask provisioning app.

    Parameters
    ----------
    credentials     : Shared dict. POST /provision writes {ssid, password} here.
    event           : threading.Event set after valid credentials are received.
    shutdown_callback : Called (in a daemon thread) after a successful POST to
                        signal the server to stop. Pass None or a MagicMock in
                        unit tests.
    """
    app = Flask(__name__)

    @app.after_request
    def add_hsts(response):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.route('/', methods=['GET'])
    def index():
        return make_response(_FORM_HTML, 200)

    @app.route('/provision', methods=['POST'])
    def provision():
        ssid = request.form.get('ssid', '').strip()
        password = request.form.get('password', '').strip()

        if not ssid or not password:
            error_reason = "SSID and password are required and must not be empty."
            return make_response(_ERROR_HTML.replace('{error_reason}', error_reason), 400)

        credentials['ssid'] = ssid
        credentials['password'] = password
        event.set()

        if shutdown_callback is not None:
            # Run in a daemon thread so the response is returned before
            # the server shuts down (calling shutdown() from within the
            # request handler would deadlock the server loop).
            threading.Thread(target=shutdown_callback, daemon=True).start()

        return make_response(_SUCCESS_HTML, 200)

    return app


# ---------------------------------------------------------------------------
# HTTPS server factory
# ---------------------------------------------------------------------------

def create_server(credentials: dict, event: threading.Event, ssl_context, port: int = 443):
    """
    Bind the Flask app to a werkzeug HTTPS server in a daemon thread.

    Parameters
    ----------
    port : Defaults to 443 (production). Pass a high port (e.g. 4433) for
           integration tests that run without root.

    Returns (werkzeug.serving.BaseWSGIServer, threading.Thread).

    provision.py joins the thread after the event fires, then calls
    create_server() again on retry — the join ensures the port is released
    before the new bind.
    """
    def _shutdown():
        srv.shutdown()

    app = create_app(credentials, event, shutdown_callback=_shutdown)
    srv = make_server('0.0.0.0', port, app, ssl_context=ssl_context)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread
