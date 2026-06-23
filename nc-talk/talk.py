"""Nextcloud Talk transport — frontend-agnostic, no note-bot logic.

Responsibilities:
  - verify incoming webhook signatures and parse events into a small dict;
  - send messages and reactions (with the bot HMAC signing scheme);
  - seed many reactions in parallel (the "chips as buttons" pattern).

Signing recipes (confirmed against the live server):
  incoming  : HMAC-SHA256(random + raw_body, secret)
  outgoing  : message -> over the message text; reaction -> over the emoji
"""

import json
import hmac
import hashlib
import socket
import secrets
import http.client
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Prefer IPv4 — avoids the slow IPv6 "happy eyeballs" timeout on the first connection.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_first(host, *args, **kwargs):
    res = _orig_getaddrinfo(host, *args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET] or res
socket.getaddrinfo = _ipv4_first

# Talk traffic must never use the (Google/TMDb) SOCKS proxy, even if those libraries
# briefly set HTTP(S)_PROXY env while we send — so use a proxy-less opener.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class TalkClient:
    def __init__(self, secret: str, internal_url: str | None = None):
        self.secret = secret.encode()
        # If set, replies go to this base URL instead of the public one from the
        # webhook header — avoids slow NAT hairpin. We keep the public Host header.
        self.internal_url = internal_url

    def sign(self, random: str, payload: str) -> str:
        return hmac.new(self.secret, (random + payload).encode(), hashlib.sha256).hexdigest()

    def verify(self, random: str, body: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(random, body), signature)

    def _headers(self, host: str, random: str, signed_content: str) -> dict:
        return {
            "Content-Type": "application/json",
            "OCS-APIRequest": "true",
            "Host": host,  # keep the public host so Nextcloud's trusted-domain check passes
            "X-Nextcloud-Talk-Bot-Random": random,
            "X-Nextcloud-Talk-Bot-Signature": self.sign(random, signed_content),
        }

    def _post(self, backend: str, path: str, signed_content: str, body: dict):
        base = (self.internal_url or backend).rstrip("/")
        random = secrets.token_hex(32)
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST")
        for k, v in self._headers(urlparse(backend).netloc, random, signed_content).items():
            req.add_header(k, v)
        try:
            with _OPENER.open(req, timeout=10) as resp:
                resp.read()  # we predict message ids ourselves; the body isn't needed
            return True
        except urllib.error.HTTPError as e:
            print(f"[talk] POST {path} -> HTTP {e.code}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[talk] POST {path} failed: {e}", flush=True)
        return None

    def send_message(self, backend: str, token: str, text: str):
        self._post(
            backend, f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}/message",
            text, {"message": text, "referenceId": secrets.token_hex(16)},
        )

    def add_reaction(self, backend: str, token: str, msg_id, emoji: str):
        self._post(
            backend, f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}/reaction/{msg_id}",
            emoji, {"reaction": emoji},
        )

    def seed_reactions(self, backend: str, token: str, msg_id, chips):
        """Add reactions in the given order over a single keep-alive connection, so
        they appear in the listed order (parallel seeding scrambles them) and stay
        fast (one TLS handshake instead of one per chip)."""
        u = urlparse(self.internal_url or backend)
        host = urlparse(backend).netloc
        path = f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}/reaction/{msg_id}"
        try:
            if u.scheme == "https":
                conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=10)
            else:
                conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
        except Exception as e:  # noqa: BLE001
            print(f"[talk] seed connect failed: {e}", flush=True)
            return
        try:
            for emoji in chips:
                random = secrets.token_hex(32)
                conn.request("POST", path, json.dumps({"reaction": emoji}),
                             self._headers(host, random, emoji))
                conn.getresponse().read()  # drain before the next request
        except Exception as e:  # noqa: BLE001
            print(f"[talk] seed failed: {e}", flush=True)
        finally:
            conn.close()


def parse_event(raw: bytes) -> dict:
    """Normalise a Talk webhook payload into a flat dict the app can switch on."""
    e = json.loads(raw)
    obj = e.get("object", {})
    ev = {
        "type": e.get("type"),                       # Create | Like | Undo
        "token": e.get("target", {}).get("id"),      # conversation token
        "actor_id": e.get("actor", {}).get("id", ""),  # users/... or bots/...
        "msg_id": obj.get("id"),                     # message this event is about
        "emoji": e.get("content"),                   # for Like/Undo: the reaction
        "text": None,                                # for Create: the message text
    }
    if ev["type"] == "Create":
        try:
            ev["text"] = json.loads(obj.get("content", "{}")).get("message", "")
        except ValueError:
            ev["text"] = ""
    return ev


def serve(port: int, client: TalkClient, on_event):
    """Run the webhook server. `on_event(ev, backend)` is called for each verified,
    non-bot event (events caused by bots — including our own seeded reactions — are
    dropped here so the app never answers itself)."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            random = self.headers.get("X-Nextcloud-Talk-Random", "")
            signature = self.headers.get("X-Nextcloud-Talk-Signature", "")
            backend = self.headers.get("X-Nextcloud-Talk-Backend", "")
            if not client.verify(random, body.decode("utf-8", "replace"), signature):
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)  # acknowledge promptly, then process
            self.end_headers()
            try:
                ev = parse_event(body)
                if ev["actor_id"].startswith("bots/"):
                    return  # our own seeded reactions / other bots
                on_event(ev, backend)
            except Exception as e:  # noqa: BLE001
                print(f"[talk] handler error: {e}", flush=True)

    print(f"[talk] listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
