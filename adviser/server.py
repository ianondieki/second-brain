"""The webhook server: Meta ─HTTPS─▶ tunnel ─▶ 127.0.0.1:PORT ─▶ queue ─▶ one worker.

    GET  /webhook   Meta's verification (hub.challenge)
    POST /webhook   events; answered 200 at once, handled in the background
    GET  /health    liveness, for the tunnel check

Meta retries any delivery that is slow or not 200 (for up to 7 days), so the
handler only checks, filters and queues; the worker thread does the slow part
(transcribe, think, speak, send). One worker keeps the owner's messages in order
and keeps the model's token budget in one place.

What is dropped without an answer: bad signatures (401), messages to another
business number, messages from anyone but the owner, repeats of a message already
handled, and messages older than 23 hours (the reply window would be closed).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import queue
import re
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import whatsapp

log = logging.getLogger("adviser")

MAX_BODY = 1024 * 1024
DRAIN_LIMIT = 4 * MAX_BODY       # how much of a refused body to read so the refusal gets through
MAX_AGE = 23 * 3600


def mask(number: str) -> str:
    return f"…{number[-3:]}" if number else "?"


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """http.server sets SO_REUSEADDR, which on Windows lets a SECOND process bind a port that
    is already listening and take some of its connections. Bind exclusively instead, so a
    second `adviser serve` fails with "port busy" rather than silently sharing the webhook."""
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AdviserServer:
    def __init__(self, env: dict, store, handle_batch, verify_token: str, host: str = "127.0.0.1",
                 port: int = 8765, clock=time.time):
        self.app_secret = env.get("WA_APP_SECRET", "")
        if not self.app_secret:
            raise ValueError("WA_APP_SECRET is not set; without it the webhook cannot tell Meta from anyone else.")
        self.owner = re.sub(r"\D", "", env.get("WA_TO") or env.get("WA_TARGET_NUMBER") or "")
        if not self.owner:
            raise ValueError("WA_TARGET_NUMBER is not set; the adviser only answers that number.")
        self.pnid = str(env.get("WA_PHONE_NUMBER_ID") or "")
        self.verify_token, self.store, self.handle_batch, self.clock = verify_token, store, handle_batch, clock
        self.queue: queue.Queue = queue.Queue()
        self.stats = {"received": 0, "queued": 0, "ignored": 0, "answered": 0, "failed": 0}
        self.public_url = ""
        self._stop = threading.Event()
        self.httpd = ExclusiveHTTPServer((host, port), _handler(self))
        self.port = self.httpd.server_address[1]
        self.worker = threading.Thread(target=self._work, daemon=True, name="adviser-worker")
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="adviser-http")

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> "AdviserServer":
        for m in self.store.leftovers(MAX_AGE):          # accepted by a previous run, never answered
            try:
                msg = whatsapp.Inbound(**{k: m[k] for k in m if k in whatsapp.Inbound.__dataclass_fields__})
            except TypeError as exc:                     # a file from an older version: drop it
                log.warning("Dropping an unreadable unfinished message: %s", exc)
                self.store.release(str(m.get("id") or ""))
                continue
            log.info("Answering message %s left unfinished by the previous run.", msg.id[-12:])
            self.queue.put(msg)
        self.worker.start()
        self.http_thread.start()
        log.info("Webhook server listening on http://127.0.0.1:%d/webhook", self.port)
        return self

    def stop(self) -> None:
        self._stop.set()
        self.queue.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------------ inbound

    def accept(self, body: bytes, signature: str | None) -> int:
        if not whatsapp.verify_signature(self.app_secret, body, signature):
            log.warning("Rejected a webhook POST with a missing or wrong signature.")
            return 401
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return 400
        messages, statuses = whatsapp.parse_webhook(payload)
        for s in statuses:
            if s.get("status") == "failed":
                errs = s.get("errors") if isinstance(s.get("errors"), list) else []
                first = errs[0] if errs and isinstance(errs[0], dict) else {}
                log.warning("A reply was not delivered: %s", str(first.get("title") or errs)[:300])
        now = self.clock()
        for m in messages:
            self.stats["received"] += 1
            why = None
            if self.pnid and m.phone_number_id and m.phone_number_id != self.pnid:
                why = "sent to another business number"
            elif m.sender != self.owner:
                why = f"from {mask(m.sender)}, not the owner"
            elif m.timestamp and now - m.timestamp > MAX_AGE:
                why = "older than 23 hours"
            elif not self.store.first_time(m.id):
                why = "already handled"
            if why:
                self.stats["ignored"] += 1
                log.info("Ignored message %s (%s).", m.id[-12:], why)
                continue
            self.stats["queued"] += 1
            try:
                self.store.hold(dataclasses.asdict(m))     # on disk before Meta gets its 200
            except OSError as exc:                      # it is already marked seen: answer it anyway
                log.warning("Could not keep message %s on disk (%s); answering it without that safety net.",
                            m.id[-12:], exc)
            self.store.note_inbound(float(m.timestamp or now))   # this is what opens WhatsApp's 24-hour window
            self.queue.put(m)
        return 200

    # ------------------------------------------------------------------ worker

    def _work(self) -> None:
        while not self._stop.is_set():
            first = self.queue.get()
            if first is None:
                break
            batch = [first]
            while True:                         # messages that arrived together make one turn
                try:
                    nxt = self.queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    self._stop.set()
                    break
                batch.append(nxt)
            try:
                self.handle_batch(batch)
                self.stats["answered"] += 1
            except BaseException:                      # the only worker must never die
                self.stats["failed"] += 1
                log.exception("Turn crashed")
            finally:
                for m in batch:
                    self.store.release(m.id)

    def health(self) -> dict:
        """What the public /health says (it is reachable through the tunnel): alive or not, nothing more."""
        return {"ok": self.worker.is_alive()}


def _handler(server: AdviserServer):
    class Handler(BaseHTTPRequestHandler):
        timeout = 20
        server_version = "second-brain-adviser"
        sys_version = ""

        def log_message(self, fmt, *args):          # keep request lines out of stderr
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _drain(self, length: int) -> None:
            """Read and throw away a body we are about to refuse. Answering while the sender is
            still writing makes Windows reset the connection, so the sender sees a dropped call
            instead of the refusal, and Meta would just keep redelivering. Bounded, so a huge
            Content-Length cannot tie this thread up."""
            left = min(max(length, 0), DRAIN_LIMIT)
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    return
                left -= len(chunk)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/webhook":
                challenge = whatsapp.verify_challenge(urllib.parse.parse_qs(url.query), server.verify_token)
                if challenge is None:
                    log.warning("Refused a webhook verification with a wrong or missing verify token.")
                    return self._send(403, b"forbidden")
                log.info("Meta verified the webhook.")
                return self._send(200, challenge.encode("utf-8"))
            if url.path == "/health":
                return self._send(200, json.dumps(server.health()).encode("utf-8"), "application/json")
            return self._send(404, b"not found")

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path != "/webhook":
                return self._send(404, b"not found")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, b"bad length")
            if length <= 0 or length > MAX_BODY:
                self._drain(length)
                return self._send(413 if length > MAX_BODY else 400, b"bad size")
            body = self.rfile.read(length)
            try:
                status = server.accept(body, self.headers.get("X-Hub-Signature-256"))
            except Exception:
                log.exception("Webhook handling crashed")
                status = 500
            return self._send(status, b"ok" if status == 200 else b"refused")

    return Handler
