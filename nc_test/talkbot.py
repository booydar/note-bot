"""
Minimal Nextcloud Talk bot — interaction-style test harness (no note-bot logic yet).

Goal: feel how fast the different Talk response types are:
  - "reaction chips as buttons": the bot posts a message and immediately reacts to
    its own message with a set of emojis. They render as tappable chips; tapping one
    is ~one tap and the bot is notified with which emoji was tapped.
  - numbered selection via keycap-emoji chips (1..5)
  - plain text replies (the typing fallback)

Stdlib only, so the Docker image is tiny and starts instantly.

It is intentionally chatty in the logs (prints every incoming payload) so we can
observe the *real* event shapes against the live server while testing.

Env:
  SECRET           shared secret used at `occ talk:bot:install` (required)
  BOT_PORT         port to listen on (default 9000)
  NC_INTERNAL_URL  optional override for the Nextcloud base URL used for replies.
                   By default we use the X-Nextcloud-Talk-Backend header the server
                   sends us (its public URL). Set this only if the public URL is not
                   reachable from inside the container (no NAT hairpin).
"""

import os
import time
import json
import hmac
import hashlib
import secrets
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SECRET = os.environ["SECRET"].encode()
PORT = int(os.environ.get("BOT_PORT", "9000"))
NC_INTERNAL_URL = os.environ.get("NC_INTERNAL_URL")  # optional
LOG_PATH = os.environ.get("LOG_FILE")  # optional: also append output here


def log(*args):
    """Print to stdout and, if LOG_FILE is set, append there too (so logs can be
    read from a bind-mounted file without needing `docker logs`)."""
    line = " ".join(str(a) for a in args)
    print(line, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

# --- the demo "buttons" ----------------------------------------------------
# Each menu maps an emoji chip -> what tapping it means. The legend is printed in
# the message text because Talk reaction chips carry no label of their own.
MENU = [
    ("📝", "note"),
    ("🎬", "film"),
    ("📺", "series"),
    ("💭", "thoughts"),
    ("🏷️", "tag"),
    ("💰", "expense"),
    ("⭐", "favorite"),
    ("🔖", "watchlist"),
    ("👁️", "watched"),
    ("🔗", "link"),
    ("📅", "today"),
    ("✅", "save"),
    ("⏭️", "next"),
    ("🔁", "redo"),
    ("❌", "cancel"),
]
LIST_CHIPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "⏭️", "✅"]


def sign(random: str, payload: str) -> str:
    """HMAC-SHA256 over (random + payload). Used for both signing our outgoing
    requests and verifying incoming ones (where payload is the raw body)."""
    return hmac.new(SECRET, (random + payload).encode(), hashlib.sha256).hexdigest()


def _base_url(backend: str) -> str:
    return (NC_INTERNAL_URL or backend).rstrip("/")


def _ocs_post(backend: str, path: str, signed_content: str, body: dict):
    """POST to the Talk bot OCS API with the bot signature headers."""
    random = secrets.token_hex(32)  # 64 hex chars
    data = json.dumps(body).encode()
    req = urllib.request.Request(_base_url(backend) + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("OCS-APIRequest", "true")
    req.add_header("X-Nextcloud-Talk-Bot-Random", random)
    req.add_header("X-Nextcloud-Talk-Bot-Signature", sign(random, signed_content))
    # Keep the public hostname in the Host header so Nextcloud's trusted-domain
    # check passes even if we connect via an internal address.
    req.add_header("Host", urlparse(backend).netloc)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read() or b"{}")
        kind = "reaction" if "/reaction/" in path else "message"
        log(f"[send] {kind} {int((time.monotonic() - t0) * 1000)}ms")
        return data
    except urllib.error.HTTPError as e:
        log(f"[send] HTTP {e.code} {path}: {e.read()[:300]!r}")
    except Exception as e:
        log(f"[send] error {path}: {e}")
    return None


def send_message(backend: str, token: str, text: str):
    """Send a chat message. Signed content is the message text. Returns new msg id."""
    resp = _ocs_post(
        backend,
        f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}/message",
        signed_content=text,
        body={"message": text, "referenceId": secrets.token_hex(16)},
    )
    try:
        return resp["ocs"]["data"]["id"]
    except (TypeError, KeyError):
        return None


def add_reaction(backend: str, token: str, message_id, emoji: str):
    """React to a message. Signed content is the emoji. This is how we 'pre-seed'
    the tappable chips under our own message."""
    _ocs_post(
        backend,
        f"/ocs/v2.php/apps/spreed/api/v1/bot/{token}/reaction/{message_id}",
        signed_content=emoji,
        body={"reaction": emoji},
    )


def reply_with_chips(backend: str, token: str, user_msg_id, text: str, chips):
    """Post a text reply, then seed reaction chips on the bot's OWN reply.

    The send API returns data:null, so we can't read the new message's id. But Talk
    ids are sequential, so in a 1-on-1 chat the bot's reply is user_msg_id + 1. We
    react to that to put the chips under the bot's answer (Telegram-like)."""
    send_message(backend, token, text)  # this becomes the next message id
    try:
        target = str(int(user_msg_id) + 1)  # the reply we just sent
    except (TypeError, ValueError):
        target = user_msg_id
    with ThreadPoolExecutor(max_workers=8) as pool:
        for emoji in chips:
            pool.submit(add_reaction, backend, token, target, emoji)


# --- handling incoming events ----------------------------------------------
def handle_event(event: dict, backend: str):
    etype = event.get("type")
    actor = event.get("actor", {})
    token = event.get("target", {}).get("id")

    # Ignore anything caused by a bot — including OUR OWN seeded reactions, which
    # come back as Like events with actor.type "Person" but actor.id "bots/...".
    # Without this the bot answers its own chips ("splurge").
    if actor.get("id", "").startswith("bots/"):
        return

    if etype == "Create":
        try:
            text = json.loads(event["object"]["content"]).get("message", "")
        except (KeyError, ValueError):
            text = ""
        msg_id = event.get("object", {}).get("id")  # the user's message — we react to it
        cmd = text.strip().lower()

        if "list" in cmd:
            text = "**Numbered selection demo** — tap a chip below 👇 to 'link', ⏭️ next, ✅ save."
            reply_with_chips(backend, token, msg_id, text, LIST_CHIPS)
        else:
            legend = "  ".join(f"{e} {label}" for e, label in MENU)
            reply_with_chips(
                backend, token, msg_id, f"Tap a chip below 👇 to choose:\n\n{legend}",
                [e for e, _ in MENU],
            )

    elif etype == "Like":
        # The reacted message is in `object`; the emoji is the top-level `content`.
        emoji = event.get("content", "?")
        send_message(backend, token, f"⚡ You tapped {emoji} — felt like a button, right?")

    elif etype == "Undo":
        emoji = event.get("content", "")
        send_message(backend, token, f"↩️ Removed {emoji}.".strip())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet the default per-request logging
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

        expected = sign(random, body.decode("utf-8", "replace"))
        if not hmac.compare_digest(expected, signature):
            log("[recv] signature mismatch — rejecting")
            self.send_response(401)
            self.end_headers()
            return

        # Acknowledge immediately, then process.
        self.send_response(200)
        self.end_headers()

        try:
            event = json.loads(body)
            log(f"[recv] {json.dumps(event)[:2000]}")
            handle_event(event, backend)
        except Exception as e:
            log(f"[recv] error handling event: {e}")


if __name__ == "__main__":
    log(f"Talk test bot listening on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
