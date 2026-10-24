import http.server
import ssl
import socket
import threading
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("Installer::PhoneCompanion")

GLOBAL_CONFIG = None
CONFIG_RECEIVED_EVENT = threading.Event()
MAX_CONFIG_BYTES = 64 * 1024

# What the companion form may set, and how long each value may be. Anything
# else in the payload is dropped (#185): the values go straight into GTK
# entries and the install recipe, so a non-string or an unexpected key must
# not reach them.
_FIELD_LIMITS = {
    "fullname": 256,
    "username": 32,
    "password": 4096,
    "hostname": 63,
    "sshkey": 16 * 1024,
}
_REQUIRED_FIELDS = ("fullname", "username", "password", "hostname")
# The same rules the installer applies to typed input: user.py for the
# username, Systeminfo hostname generation for the hostname.
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def sanitize_config(raw):
    """The companion payload reduced to known string fields, or None.

    None means reject the submission: a required field is missing or empty,
    a value is not a string or is too long, or the username or hostname is
    not one the installer would accept if typed.
    """
    if not isinstance(raw, dict):
        return None
    config = {}
    for key, limit in _FIELD_LIMITS.items():
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            return None
        config[key] = value
    config["hostname"] = config["hostname"].strip().lower()
    config["username"] = config["username"].strip()
    if any(not config[key] for key in _REQUIRED_FIELDS):
        return None
    if not _USERNAME_RE.match(config["username"]):
        return None
    if not _HOSTNAME_RE.match(config["hostname"]):
        return None
    return config

def get_local_ip():
    """Finds the local IP address of the primary active interface."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # Fallback
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def render_companion_html(name=None, hostname=None):
    """COMPANION_HTML with the product name and hostname stem filled in from
    the branding contract (shared/branding/README.md); never a literal."""
    if name is None or hostname is None:
        from bootc_installer.utils import branding
        b = branding.resolve()
        name = name or b.name
        hostname = hostname or b.default_hostname
    return COMPANION_HTML.replace("__PRODUCT__", name).replace("__HOSTNAME__", hostname)


# Premium Dark-Mode HTML Form to serve on mobile devices
COMPANION_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__PRODUCT__ Installer Companion</title>
    <style>
        :root {
            --bg-color: #0b0b0f;
            --card-bg: rgba(26, 26, 36, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-color: #f3f4f6;
            --text-dim: #9ca3af;
            --primary: #3b82f6;
            --primary-glow: rgba(59, 130, 246, 0.5);
            --success: #10b981;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 440px;
            padding: 24px;
            box-sizing: border-box;
        }

        .card {
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 32px 24px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .card::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            background: linear-gradient(135deg, var(--primary), transparent, transparent);
            border-radius: 24px;
            z-index: -1;
            opacity: 0.3;
        }

        h1 {
            font-size: 24px;
            margin: 0 0 8px 0;
            font-weight: 700;
        }

        p.subtitle {
            color: var(--text-dim);
            font-size: 14px;
            margin: 0 0 28px 0;
        }

        .form-group {
            text-align: left;
            margin-bottom: 20px;
        }

        label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        input, textarea {
            width: 100%;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 16px;
            box-sizing: border-box;
            color: var(--text-color);
            font-size: 15px;
            transition: all 0.2s ease;
        }

        input:focus, textarea:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 8px var(--primary-glow);
        }

        button {
            width: 100%;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 10px;
            transition: all 0.2s ease;
        }

        button:active {
            transform: scale(0.98);
        }

        #success-state {
            display: none;
        }

        .success-icon {
            font-size: 48px;
            color: var(--success);
            margin-bottom: 16px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card" id="form-state">
            <h1>__PRODUCT__ Setup</h1>
            <p class="subtitle">Complete your installation settings from your phone</p>
            
            <div class="form-group">
                <label for="fullname">Full Name</label>
                <input type="text" id="fullname" placeholder="e.g. John Doe" required>
            </div>
            
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" placeholder="e.g. johndoe" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" placeholder="Create user password" required>
            </div>
            
            <div class="form-group">
                <label for="hostname">Hostname</label>
                <input type="text" id="hostname" placeholder="e.g. __HOSTNAME__-desktop" value="__HOSTNAME__-desktop" required>
            </div>
            
            <div class="form-group">
                <label for="sshkey">SSH Public Key (Optional)</label>
                <textarea id="sshkey" rows="3" placeholder="ssh-rsa ..."></textarea>
            </div>
            
            <button onclick="submitConfig()">Submit Setup</button>
        </div>

        <div class="card" id="success-state">
            <div class="success-icon">✓</div>
            <h1>Setup Completed!</h1>
            <p class="subtitle">You can now look back at the installer screen to confirm and finish the installation.</p>
        </div>
    </div>

    <script>
        // The QR code carries the session token in ?token= so the page itself
        // can be fetched. Keep it in memory only and drop it from the address
        // bar and this history entry, so it does not linger in the phone's
        // browser history; the submission sends it in a header, not a URL
        // (#227). Scan the QR code again to reopen the form.
        const companionToken = new URLSearchParams(window.location.search).get('token') || '';
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', window.location.pathname);
        }

        // Auto-suggest username from full name
        document.getElementById('fullname').addEventListener('input', function(e) {
            const name = e.target.value.toLowerCase();
            const username = name.replace(/[^a-z0-9]/g, '');
            document.getElementById('username').value = username;
        });

        function submitConfig() {
            const fullname = document.getElementById('fullname').value;
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const hostname = document.getElementById('hostname').value;
            const sshkey = document.getElementById('sshkey').value;

            if (!fullname || !username || !password || !hostname) {
                alert('Please fill out all required fields');
                return;
            }

            const payload = {
                fullname: fullname,
                username: username,
                password: password,
                hostname: hostname,
                sshkey: sshkey
            };

            fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + companionToken
                },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    document.getElementById('form-state').style.display = 'none';
                    document.getElementById('success-state').style.display = 'block';
                } else {
                    alert('Submission failed, please try again.');
                }
            })
            .catch(err => {
                console.error(err);
                alert('Connection error.');
            });
        }
    </script>
</body>
</html>
"""

class CompanionRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP logging in the installer logs
        pass

    def _token_matches(self, supplied):
        expected = getattr(self.server, "auth_token", None)
        if not expected or not isinstance(supplied, str):
            return False
        return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _authorized_path(self, from_header=False):
        """The request path if the session token is valid, else None (403).

        The page is opened from the QR code, so a GET carries the token in
        ?token=. The submission must send it as `Authorization: Bearer`, never
        in the URL, so the token is not repeated in request lines (#227).
        """
        parsed = urlparse(self.path)
        if from_header:
            header = self.headers.get("Authorization") or ""
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer":
                supplied = ""
        else:
            supplied = parse_qs(parsed.query).get("token", [""])[0]
        if not self._token_matches(supplied.strip()):
            self.send_error(403, "Forbidden")
            return None
        return parsed.path

    def do_GET(self):
        path = self._authorized_path()
        if path is None:
            return
        if path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            # The page was fetched with the token in its URL: never cache it,
            # and never send that URL on as a Referer.
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(render_companion_html().encode('utf-8'))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        path = self._authorized_path(from_header=True)
        if path is None:
            return
        if path == "/api/config":
            # One submission per session. The page polls for the first one
            # and stops the server; a second POST in between must not swap
            # the account details the user just sent.
            if CONFIG_RECEIVED_EVENT.is_set():
                self.send_error(409, "Configuration already received")
                return
            try:
                content_length = int(self.headers['Content-Length'])
                if content_length > MAX_CONFIG_BYTES:
                    self.send_error(413, "Request body too large")
                    return
                post_data = self.rfile.read(content_length)
                config = sanitize_config(json.loads(post_data.decode('utf-8')))
                if config is None:
                    raise ValueError("payload failed validation")
                
                global GLOBAL_CONFIG
                GLOBAL_CONFIG = config
                CONFIG_RECEIVED_EVENT.set()
                # The token is single-use: once the details are in, a copy of
                # the QR code or the link opens nothing (#227).
                self.server.auth_token = None
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"success"}')
            except Exception as e:
                logger.error("Failed to parse POST payload: %s", e)
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"status":"error"}')
        else:
            self.send_error(404, "Not Found")

def generate_self_signed_cert():
    """Generate a one-day self-signed certificate with openssl.

    Returns (certfile, keyfile) in a fresh private directory, or None. The
    key used to be written to fixed paths in /tmp, where another account on
    the machine could pre-create them.
    """
    certdir = tempfile.mkdtemp(prefix="bootc-companion-")  # mode 0700
    cert = os.path.join(certdir, "cert.pem")
    key = os.path.join(certdir, "key.pem")
    try:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key,
            "-out", cert,
            "-days", "1", "-nodes",
            "-subj", "/CN=bootc-companion"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cert, key
    except Exception as e:
        logger.warning("Could not generate a self-signed certificate: %s", e)
        return None

class CompanionServer:
    def __init__(self, port=8443):
        self.port = port
        self.server = None
        self.thread = None
        self.is_https = False
        self.auth_token = None

    def start(self) -> bool:
        """Serve the companion form over HTTPS. Returns whether it is up.

        There is no plain-HTTP fallback: the form carries the user's
        password, and sending it across the LAN in clear text is worse than
        not offering the phone at all (#185). Without a certificate the
        page tells the user to set up on this screen instead.
        """
        global GLOBAL_CONFIG
        GLOBAL_CONFIG = None
        CONFIG_RECEIVED_EVENT.clear()
        self.auth_token = secrets.token_urlsafe(32)

        cert = generate_self_signed_cert()
        self.is_https = cert is not None
        if not self.is_https:
            logger.warning("Phone Companion disabled: no TLS certificate, and it will not serve the password over HTTP")
            self.auth_token = None
            return False

        try:
            self.server = http.server.HTTPServer(("0.0.0.0", self.port), CompanionRequestHandler)
            self.server.auth_token = self.auth_token

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert[0], keyfile=cert[1])
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            logger.info("Started local HTTPS Phone Companion server on port %s", self.port)

            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return True
        except Exception as e:
            logger.error("Failed to start CompanionServer: %s", e)
            self.server = None
            self.auth_token = None
            return False

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            logger.info("Stopped Phone Companion server")
        self.auth_token = None

    def get_config(self):
        return GLOBAL_CONFIG
