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

_FORM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Teton Device Setup</title></head>
<body>
  <h1>Teton Device Setup</h1>
  <form method="POST" action="/provision">
    <label>Wi-Fi Network (SSID)
      <input type="text" name="ssid" required autofocus>
    </label><br>
    <label>Password
      <input type="password" name="password" required>
    </label><br>
    <button type="submit">Provision</button>
  </form>
</body>
</html>
"""

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Provisioning complete</title></head>
<body>
  <h1>Provisioning complete</h1>
  <p>The device is connecting to your network. You may close this page.</p>
</body>
</html>
"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Provisioning error</title></head>
<body>
  <h1>Provisioning error</h1>
  <p>{error_reason}</p>
  <p><a href="/">Try again</a></p>
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
            return make_response(_ERROR_HTML.format(error_reason=error_reason), 400)

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
