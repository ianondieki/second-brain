"""A public HTTPS address for the webhook, kept alive and registered with Meta.

Meta can only deliver messages to a public HTTPS URL, and the laptop sits behind
NAT. ngrok cannot connect from this laptop (Avast re-signs its TLS and ngrok
refuses the certificate), so this uses a Cloudflare quick tunnel: free, no
account, QUIC over UDP (which Avast does not intercept). Its hostname
(*.trycloudflare.com) changes every time cloudflared starts, so after each start
the new callback URL is registered with Meta through the Graph API:

    POST /{app-id}/subscriptions        app webhook: object=whatsapp_business_account, fields=messages
    POST /{waba-id}/subscribed_apps     the WhatsApp Business Account sends its events to the app

The first call needs an app access token, "{app-id}|{app-secret}". The app id is
read from the system-user token when WA_APP_ID is not set.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from reminder.notify import DEFAULT_GRAPH_VERSION, USER_AGENT, tls_context

from .whatsapp import GRAPH_BASE, error_body

log = logging.getLogger("adviser")

START_TIMEOUT = 60              # cloudflared usually has a hostname within 5-10 seconds
REGISTER_TRIES = 7              # Meta's verification of a brand-new hostname can fail until its DNS
REGISTER_EVERY = 15             # has spread: retry for about 90 s before starting a new tunnel
CHECK_EVERY = 120               # ask cloudflared whether it is still connected this often
MAX_BACKOFF = 300


class RegistrationError(RuntimeError):
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_cloudflared(env: dict, base_dir: str) -> str | None:
    for candidate in (env.get("ADVISER_CLOUDFLARED"), shutil.which("cloudflared"),
                      os.path.join(base_dir, "tools", "cloudflared.exe"),
                      os.path.join(base_dir, "tools", "cloudflared")):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _get(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = tls_context() if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        return exc.code, error_body(exc).encode("utf-8")


class QuickTunnel:
    """One cloudflared process. start() returns the public https:// URL."""

    def __init__(self, exe: str, port: int, log_path: str, popen=subprocess.Popen, get=_get,
                 clock=time.time, sleep=time.sleep, run=subprocess.run):
        self.exe, self.port, self.log_path = exe, port, log_path
        self.popen, self.get, self.clock, self.sleep, self.run = popen, get, clock, sleep, run
        self.pid_path = os.path.join(os.path.dirname(log_path), f"cloudflared-{port}.pid")
        self.proc = None
        self.url = ""
        self.metrics = 0

    def _kill_leftover(self) -> None:
        """Windows does not end a child when its parent dies: if the adviser was killed, its
        cloudflared is still running. Stop it, but only if that PID is still OUR tunnel (same
        cloudflared.exe, same local port): PIDs get reused, and other programs on this laptop
        run their own cloudflared."""
        try:
            with open(self.pid_path, encoding="utf-8") as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            cmdline = self.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                               capture_output=True, text=True, timeout=30, creationflags=flags).stdout or ""
            ours = (os.path.normcase(os.path.abspath(self.exe)) in os.path.normcase(cmdline)
                    and re.search(rf"http://127\.0\.0\.1:{self.port}(?!\d)", cmdline) is not None)
            if ours:
                self.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=15, creationflags=flags)
                log.info("Stopped this adviser's cloudflared (pid %d) left over from an earlier run.", pid)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Could not check for a leftover cloudflared: %s", exc)
        try:
            os.remove(self.pid_path)
        except OSError:
            pass

    def ready(self) -> bool:
        """cloudflared's own answer, on this machine: is the tunnel connected to Cloudflare's edge?
        (Checking the public hostname from here is unreliable: Windows caches the "no such host"
        answer it got in the first seconds, before the name existed.)"""
        if not self.alive() or not self.metrics:
            return False
        try:
            status, _ = self.get(f"http://127.0.0.1:{self.metrics}/ready", 5.0)
            return status == 200
        except OSError:
            return False

    def start(self) -> str:
        self.stop()
        if os.name == "nt":
            self._kill_leftover()
        metrics = self.metrics = free_port()
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        if os.path.exists(os.path.abspath(self.exe)):
            self.exe = os.path.abspath(self.exe)          # the leftover check compares full paths
        args = [self.exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}",
                "--metrics", f"127.0.0.1:{metrics}", "--logfile", self.log_path, "--loglevel", "info"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = self.popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            with open(self.pid_path, "w", encoding="utf-8") as fh:
                fh.write(str(getattr(self.proc, "pid", "")))
        except OSError:
            pass
        deadline = self.clock() + START_TIMEOUT
        while self.clock() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"cloudflared exited with code {self.proc.returncode}; see {self.log_path}")
            try:
                status, body = self.get(f"http://127.0.0.1:{metrics}/quicktunnel", 3.0)
                host = json.loads(body.decode("utf-8") or "{}").get("hostname", "") if status == 200 else ""
            except (OSError, ValueError):
                host = ""
            if host:
                self.url = f"https://{host}"
                return self.url
            self.sleep(1.0)
        self.stop()
        raise RuntimeError(f"cloudflared gave no public address within {START_TIMEOUT}s; see {self.log_path}")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc is not None:
            try:
                os.remove(self.pid_path)
            except OSError:
                pass
        self.proc = None


# --------------------------------------------------------------------------- Meta registration

def _graph(method: str, url: str, form: dict | None = None, token: str = "", timeout: float = 30.0) -> dict:
    data = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")     # never follows a redirect
    ctx = tls_context() if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = error_body(exc)
        try:
            err = json.loads(raw).get("error", {})
            msg = f"code {err.get('code')}: {err.get('message')}"
        except (ValueError, AttributeError):
            msg = raw[:300]
        raise RegistrationError(f"Meta refused {method} {urllib.parse.urlsplit(url).path}: HTTP {exc.code}, {msg}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RegistrationError(f"Could not reach Meta: {type(exc).__name__}: {exc}") from exc
    return body if isinstance(body, dict) else {}


def app_id(env: dict, base: str = GRAPH_BASE) -> str:
    if env.get("WA_APP_ID"):
        return env["WA_APP_ID"].strip()
    token = env["WA_ACCESS_TOKEN"]
    version = env.get("WA_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION
    q = urllib.parse.urlencode({"input_token": token})
    data = _graph("GET", f"{base}/{version}/debug_token?{q}", token=token).get("data") or {}
    found = str(data.get("app_id") or "")
    if not found:
        raise RegistrationError("Could not work out the Meta app id from WA_ACCESS_TOKEN; set WA_APP_ID in .env.")
    return found


def register(env: dict, callback_url: str, verify_token: str, base: str | None = None) -> str:
    """Point the app's WhatsApp webhook at callback_url and make sure the WABA sends to the app.
    Meta calls callback_url (GET, hub.challenge) during the first request, so the server must
    already be answering there. Returns the app id."""
    base = (base or env.get("WA_GRAPH_BASE") or GRAPH_BASE).rstrip("/")
    version = env.get("WA_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION
    aid = app_id(env, base)
    result = _graph("POST", f"{base}/{version}/{aid}/subscriptions", {
        "object": "whatsapp_business_account", "callback_url": callback_url, "verify_token": verify_token,
        "fields": "messages", "include_values": "true", "access_token": f"{aid}|{env['WA_APP_SECRET']}"})
    if not result.get("success"):
        raise RegistrationError(f"Meta did not confirm the webhook: {result}")
    result = _graph("POST", f"{base}/{version}/{env['WA_BUSINESS_ACCOUNT_ID']}/subscribed_apps",
                    {}, token=env["WA_ACCESS_TOKEN"])
    if not result.get("success"):
        raise RegistrationError(f"Meta did not subscribe the app to the WhatsApp account: {result}")
    return aid


# --------------------------------------------------------------------------- supervisor

class PublicEndpoint(threading.Thread):
    """Keeps a tunnel up and registered with Meta.

    1. start cloudflared, wait until it says it is connected (its local /ready);
    2. register the new URL; Meta's own verification call is the real "reachable from the
       internet" test, so a failure is retried for about 90 s while the new name spreads;
    3. watch /ready; on cloudflared exiting or 3 failed checks, start over with a new tunnel."""

    def __init__(self, tunnel: QuickTunnel, register_fn, on_url=lambda url: None,
                 clock=time.time, sleep=time.sleep, register_tries: int = REGISTER_TRIES):
        super().__init__(daemon=True, name="public-endpoint")
        self.tunnel, self.register_fn, self.on_url = tunnel, register_fn, on_url
        self.clock, self.sleep, self.register_tries = clock, sleep, register_tries
        self.stopping = threading.Event()
        self.url = ""
        self.registered_at = 0.0
        self.last_error = ""

    def stop(self) -> None:
        self.stopping.set()
        self.tunnel.stop()

    def _wait(self, seconds: float) -> bool:
        """Sleep in small steps; True if asked to stop."""
        end = self.clock() + seconds
        while self.clock() < end:
            if self.stopping.is_set():
                return True
            self.sleep(min(2.0, max(end - self.clock(), 0.01)))
        return self.stopping.is_set()

    def _until_ready(self, timeout: float) -> bool:
        end = self.clock() + timeout
        while self.clock() < end:
            if self.tunnel.ready():
                return True
            if self.stopping.is_set() or not self.tunnel.alive():
                return False
            self.sleep(1.0)
        return False

    def run_once(self) -> None:
        url = self.tunnel.start()
        log.info("Tunnel up at %s; waiting for it to connect...", url)
        if not self._until_ready(START_TIMEOUT):
            raise RuntimeError(f"{url} never connected to Cloudflare")
        if self.register_fn is None:                    # serve --no-register
            self.url, self.registered_at, self.last_error = url, self.clock(), ""
            self.on_url(url)
            log.info("Tunnel ready at %s/webhook (NOT registered with Meta: --no-register).", url)
            return self._watch(url)
        for attempt in range(1, self.register_tries + 1):
            try:
                self.register_fn(f"{url}/webhook")
                break
            except RegistrationError as exc:
                if attempt == self.register_tries:
                    raise
                log.info("Meta could not verify %s yet (%s); retrying in %ds.", url, exc, REGISTER_EVERY)
                if self._wait(REGISTER_EVERY):
                    return
        self.url, self.registered_at, self.last_error = url, self.clock(), ""
        self.on_url(url)
        log.info("Webhook registered with Meta: %s/webhook", url)
        self._watch(url)

    def _watch(self, url: str) -> None:
        """Until told to stop: return quietly; on cloudflared dying or disconnecting: raise."""
        failures, last_check = 0, self.clock()
        while not self.stopping.is_set() and self.tunnel.alive():
            if self._wait(5):
                return
            if self.clock() - last_check >= CHECK_EVERY:
                last_check = self.clock()
                failures = 0 if self.tunnel.ready() else failures + 1
                if failures >= 3:
                    raise RuntimeError(f"{url} lost its connection to Cloudflare (3 checks in a row)")
        if not self.stopping.is_set():
            raise RuntimeError("cloudflared stopped")

    def run(self) -> None:
        backoff = 15
        while not self.stopping.is_set():
            started = self.clock()
            try:
                self.run_once()
            except Exception as exc:
                if self.registered_at >= started:        # it worked for a while: start gently again
                    backoff = 15
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.error("Public endpoint problem: %s. Retrying in %ds.", self.last_error, backoff)
                self.tunnel.stop()
                if self._wait(backoff):
                    break
                backoff = min(backoff * 2, MAX_BACKOFF)
        self.tunnel.stop()
