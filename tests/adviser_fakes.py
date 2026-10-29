"""Fakes shared by the adviser tests: a local stand-in for Meta's Graph API, scripted chat
models, tone audio, and a temp second-brain folder with a couple of projects."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from adviser.server import ExclusiveHTTPServer

SECRET = "app-secret-123"
# What gpt-oss-120b really wrote in a voice reply on 2026-09-22: code wrapped in [[ ]] instead of after [[text]].
LIVE_WRAPPED_REPLY = 'Set up a tiny scheduler first. Want me to walk you through the exact code skeleton for that 15-minute setup?[[\npip install APScheduler==3.10.4\n*schedule_brief.py*\nfrom apscheduler.schedulers.blocking import BlockingScheduler\nimport pytz\n\ntz = pytz.timezone("Africa/Nairobi")\nscheduler = BlockingScheduler(timezone=tz)\n\ndef send_brief():\n    brief = run_proactive_brief()\n    notifier.show_toast("Morning Brief", brief, duration=10)\n\nscheduler.add_job(send_brief, "cron", hour=8, minute=0)\nscheduler.start()\n]]'
OWNER = "254700000001"
PNID = "111222333"
WABA = "444555666"


def retry_reset(fn, *a, **kw):
    """Call fn again if loopback drops the connection. Seen only under heavy load on the owner's
    laptop (WinError 10054, often after a ~25 s hang; antivirus traffic filtering is the likely
    cause); what the tests check is the protocol, not loopback reliability. One retry was not
    enough: a run of the whole suite while the laptop was busy still lost a test. Any other
    failure is not retried, and a reset on the last attempt is raised."""
    for wait in (0.3, 1.0, 2.5, None):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            chain = [exc, exc.__cause__, getattr(exc, "reason", None)]
            if wait is None or not any(isinstance(e, ConnectionResetError) for e in chain):
                raise
            time.sleep(wait)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def env(**over) -> dict:
    e = {"WA_ACCESS_TOKEN": "sys-token", "WA_PHONE_NUMBER_ID": PNID, "WA_BUSINESS_ACCOUNT_ID": WABA,
         "WA_TARGET_NUMBER": "+" + OWNER, "WA_APP_SECRET": SECRET, "GROQ_API_KEY": "gsk-test"}
    e.update(over)
    return e


def webhook(*messages, pnid=PNID, statuses=None) -> dict:
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "15550000000", "phone_number_id": pnid},
             "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER}],
             "messages": list(messages)}
    if statuses:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account",
            "entry": [{"id": WABA, "changes": [{"value": value, "field": "messages"}]}]}


def text_msg(mid: str, body: str, sender: str = OWNER, ts: int | None = None, reply_to: str = "") -> dict:
    m = {"from": sender, "id": mid, "timestamp": str(ts or int(time.time())), "type": "text", "text": {"body": body}}
    if reply_to:
        m["context"] = {"from": "15550000000", "id": reply_to}
    return m


def voice_msg(mid: str, media_id: str = "media-1", sender: str = OWNER, voice: bool = True) -> dict:
    return {"from": sender, "id": mid, "timestamp": str(int(time.time())), "type": "audio",
            "audio": {"mime_type": "audio/ogg; codecs=opus", "sha256": "x", "id": media_id, "voice": voice}}


def tone(seconds: float = 0.5, rate: int = 24000, fmt: str = "WAV") -> bytes:
    import numpy as np
    import soundfile as sf
    t = np.arange(int(seconds * rate)) / rate
    buf = io.BytesIO()
    sf.write(buf, (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32"), rate, format=fmt)
    return buf.getvalue()


def tool_call(name, call_id=None, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{name}",
                                              "type": "tool_call"}])


class ScriptedLLM(GenericFakeChatModel):
    """Replays scripted replies and records every message list it was given."""
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def scripted(*replies) -> ScriptedLLM:
    msgs = [r if isinstance(r, AIMessage) else AIMessage(content=r) for r in replies]
    return ScriptedLLM(messages=iter(msgs), seen=[])


class RateLimited(Exception):
    status_code = 429

    class response:                                   # noqa: N801 - mimics the SDK's shape
        status_code = 429
        headers = {"retry-after": "7"}


class FailingLLM(GenericFakeChatModel):
    exc: object = None
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        raise self.exc or RateLimited("rate limited")


def failing(exc=None) -> FailingLLM:
    return FailingLLM(messages=iter([]), exc=exc)


class TempBrain(unittest.TestCase):
    """A throwaway second-brain folder: reminders.json + two projects under projects/."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sb-adviser-")
        self.root = os.path.join(self.base, "projects")
        self.write("projects/soc-agents/README.md", "# NOC agents\n- [x] triage\n- [ ] write the runbook page\n")
        self.write("projects/soc-agents/app.py", "API_KEY = 'sk-live-1'\ndef main():\n    return 'noc'\n")
        self.write("projects/portfolio/README.md", "# Portfolio site\nAll done.\n")
        self.write("projects/portfolio/.env", "SECRET=1\n")
        old = time.time() - 10 * 86400
        for dirpath, _, files in os.walk(os.path.join(self.root, "portfolio")):
            for f in files:
                os.utime(os.path.join(dirpath, f), (old, old))
        self.write("reminders.json", json.dumps({
            "_help": "test settings", "projects_roots": [self.root], "cold_after_days": 3,
            "ignore": [], "track": [], "done": [], "snooze": {}, "notes": {}}, indent=2))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write(self, rel, content):
        p = os.path.join(self.base, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)

    def read_json(self, rel):
        with open(os.path.join(self.base, *rel.split("/")), encoding="utf-8") as fh:
            return json.load(fh)


class FakeClient:
    """Records what the adviser would send to WhatsApp."""

    def __init__(self, media: bytes = b"OggS-fake", fail_voice: bool = False):
        self.calls, self.media, self.fail_voice = [], media, fail_voice

    def mark_read(self, message_id, typing=True):
        self.calls.append(("read", message_id, typing))

    def download(self, media_id):
        self.calls.append(("download", media_id))
        return self.media, "audio/ogg"

    def send_text(self, to, body):
        self.calls.append(("text", to, body))
        return f"wamid.text{len(self.calls)}"

    def send_voice(self, to, ogg):
        if self.fail_voice:
            from reminder.notify import DeliveryError
            raise DeliveryError("upload failed")
        self.calls.append(("voice", to, ogg))
        return f"wamid.voice{len(self.calls)}"

    def kinds(self):
        return [c[0] for c in self.calls]

    def texts(self):
        return [c[2] for c in self.calls if c[0] == "text"]


# --------------------------------------------------------------------------- a local Graph API

class FakeGraph:
    """Answers the Graph API calls the adviser makes, on http://127.0.0.1:<port>, and records them.
    On POST /{app}/subscriptions it does what Meta does: a verification GET to the callback."""

    def __init__(self, media: bytes = b"voice-bytes", verify_callbacks: bool = True):
        self.requests, self.uploads, self.sent, self.media = [], [], [], media
        self.verify_callbacks = verify_callbacks
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, status, obj=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(obj or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                with fake.lock:
                    fake.requests.append(("GET", u.path, self.headers.get("Authorization"), None))
                if u.path.startswith("/files/"):
                    if self.headers.get("Authorization") != "Bearer sys-token":
                        return self._reply(401, {"error": {"code": 190, "message": "no token"}})
                    return self._reply(200, raw=fake.media, ctype="audio/ogg")
                if u.path.endswith("/debug_token"):
                    return self._reply(200, {"data": {"app_id": "999000"}})
                media_id = u.path.rsplit("/", 1)[-1]
                return self._reply(200, {"url": f"http://127.0.0.1:{fake.port}/files/{media_id}",
                                         "mime_type": "audio/ogg; codecs=opus", "file_size": len(fake.media),
                                         "id": media_id})

            def do_POST(self):
                u = urllib.parse.urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                ctype = self.headers.get("Content-Type", "")
                with fake.lock:
                    fake.requests.append(("POST", u.path, self.headers.get("Authorization"), body))
                if u.path.endswith("/media"):
                    with fake.lock:
                        fake.uploads.append((ctype, body))
                        return self._reply(200, {"id": f"up-{len(fake.uploads)}"})
                if u.path.endswith("/messages"):
                    payload = json.loads(body)
                    with fake.lock:
                        fake.sent.append(payload)
                        n = len(fake.sent)
                    if payload.get("status") == "read":
                        return self._reply(200, {"success": True})
                    return self._reply(200, {"messages": [{"id": f"wamid.out{n}"}]})
                if u.path.endswith("/subscriptions"):
                    form = dict(urllib.parse.parse_qsl(body.decode()))
                    if fake.verify_callbacks:
                        q = urllib.parse.urlencode({"hub.mode": "subscribe", "hub.challenge": "8675309",
                                                    "hub.verify_token": form.get("verify_token", "")})
                        try:
                            with urllib.request.urlopen(f"{form['callback_url']}?{q}", timeout=20) as r:
                                ok = r.status == 200 and r.read() == b"8675309"
                        except Exception:
                            ok = False
                        if not ok:
                            return self._reply(400, {"error": {"code": 2200, "message": "Callback verification failed"}})
                    return self._reply(200, {"success": True})
                if u.path.endswith("/subscribed_apps"):
                    return self._reply(200, {"success": True})
                return self._reply(404, {"error": {"code": 100, "message": "unknown path"}})

        self.httpd = ExclusiveHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def wait_for(self, predicate, timeout=20.0):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if predicate(self):
                    return True
            time.sleep(0.05)
        return False
