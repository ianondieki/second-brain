"""Webhook server, the full pipeline over real HTTP against a fake Graph API, Meta
registration, and the tunnel supervisor (no internet, no real WhatsApp).

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_server -v
"""
import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

import soundfile as sf

from adviser import brain, memory, speech, tunnel, turn
from adviser.server import AdviserServer
from adviser.whatsapp import Client
from tests.adviser_fakes import (OWNER, PNID, FakeGraph, TempBrain, env, retry_reset, scripted, sign, text_msg,
                                 tone, voice_msg, webhook)


def post(url, payload, signature=True, raw=None):
    return retry_reset(_post, url, payload, signature, raw)


def _post(url, payload, signature=True, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Hub-Signature-256"] = sign(body) if signature is True else signature
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def get(url):
    return retry_reset(_get, url)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class ServerTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.batches = []
        self.done = threading.Event()

        def handle(batch):
            self.batches.append([m.id for m in batch])
            self.done.set()
        self.server = AdviserServer(env(), memory.Store(self.base), handle, "verify-me", port=0).start()
        self.url = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        super().tearDown()

    def wait_handled(self, n):
        end = time.time() + 5
        while time.time() < end and sum(len(b) for b in self.batches) < n:
            time.sleep(0.02)
        return [i for b in self.batches for i in b]

    def test_verification_handshake(self):
        ok = f"{self.url}/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=12345"
        self.assertEqual(get(ok), (200, b"12345"))
        self.assertEqual(get(ok.replace("verify-me", "wrong"))[0], 403)
        status, body = get(f"{self.url}/health")
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))
        self.assertEqual(get(f"{self.url}/other")[0], 404)

    def test_owner_messages_are_queued_once(self):
        payload = webhook(text_msg("wamid.A", "hello"))
        self.assertEqual(post(f"{self.url}/webhook", payload), 200)
        self.assertEqual(post(f"{self.url}/webhook", payload), 200)          # Meta retry: same id
        self.assertEqual(self.wait_handled(1), ["wamid.A"])
        time.sleep(0.2)
        self.assertEqual(self.server.stats["ignored"], 1)

    def test_signature_is_required(self):
        payload = webhook(text_msg("wamid.B", "hi"))
        self.assertEqual(post(f"{self.url}/webhook", payload, signature=False), 401)
        self.assertEqual(post(f"{self.url}/webhook", payload, signature="sha256=" + "0" * 64), 401)
        body = json.dumps(payload).encode()
        self.assertEqual(post(f"{self.url}/webhook", None, signature=sign(body), raw=body + b" "), 401)
        self.assertEqual(self.server.stats["received"], 0)

    def test_strangers_old_messages_and_other_numbers_are_ignored(self):
        old = int(time.time()) - 24 * 3600
        for payload in (webhook(text_msg("s1", "hi", sender="254799999999")),
                        webhook(text_msg("s2", "hi", ts=old)),
                        webhook(text_msg("s3", "hi"), pnid="000")):
            self.assertEqual(post(f"{self.url}/webhook", payload), 200)
        time.sleep(0.3)
        self.assertEqual(self.batches, [])
        self.assertEqual(self.server.stats["ignored"], 3)

    def test_bad_bodies(self):
        self.assertEqual(post(f"{self.url}/webhook", None, raw=b"{not json"), 400)
        self.assertEqual(post(f"{self.url}/webhook", webhook(statuses=[{"status": "read"}])), 200)
        # An oversized body must still get an answer. Refusing it without reading it makes Windows
        # reset the connection, so the sender sees a dropped call instead of the refusal and Meta
        # would redeliver it for ever.
        big = b"x" * (1024 * 1024 + 1)
        self.assertEqual(post(f"{self.url}/webhook", None, raw=big), 413)
        self.assertEqual(post(f"{self.url}/webhook", webhook(statuses=[{"status": "read"}])), 200)  # still serving

    def test_many_messages_all_handled_in_order(self):
        payload = webhook(*[text_msg(f"m{i}", f"part {i}") for i in range(5)])
        self.assertEqual(post(f"{self.url}/webhook", payload), 200)
        self.assertEqual(self.wait_handled(5), [f"m{i}" for i in range(5)])

    def test_a_second_server_cannot_take_the_same_port(self):
        with self.assertRaises(OSError):
            AdviserServer(env(), memory.Store(self.base), print, "t", port=self.server.port)
        self.assertEqual(get(f"{self.url}/health")[0], 200)                # the first one still answers

    def test_public_health_says_only_alive(self):
        status, body = get(f"{self.url}/health")
        self.assertEqual(json.loads(body), {"ok": True})              # no message counts through the tunnel

    def test_accepted_message_stays_on_disk_until_its_turn_ends(self):
        import os
        release, seen = threading.Event(), []

        def slow(batch):
            seen.append([m.id for m in batch])
            release.wait(10)
        store = memory.Store(self.base)
        srv = AdviserServer(env(), store, slow, "t", port=0).start()
        try:
            self.assertEqual(post(f"http://127.0.0.1:{srv.port}/webhook", webhook(text_msg("wamid.H", "hi"))), 200)
            inbox = os.path.join(self.base, ".state", "adviser", "inbox")
            self.assertEqual(len(os.listdir(inbox)), 1)                 # on disk while the turn runs
            release.set()
            end = time.time() + 5
            while os.listdir(inbox) and time.time() < end:
                time.sleep(0.02)
            self.assertEqual(os.listdir(inbox), [])
        finally:
            release.set()
            srv.stop()

    def test_unfinished_messages_are_answered_after_a_restart(self):
        import dataclasses
        import os
        from adviser.whatsapp import Inbound
        store = memory.Store(self.base)
        now = int(time.time())
        store.hold(dataclasses.asdict(Inbound(id="wamid.LOST", sender=OWNER, timestamp=now, kind="text", text="hi")))
        store.hold(dataclasses.asdict(Inbound(id="wamid.OLD", sender=OWNER, timestamp=now - 24 * 3600, kind="text",
                                              text="too old")))
        store.hold(dataclasses.asdict(Inbound(id="wamid.POISON", sender=OWNER, timestamp=now, kind="text", text="x")))
        poison = store._inbox_path("wamid.POISON")                    # it already failed twice: drop it
        with open(poison, encoding="utf-8") as fh:
            held = json.load(fh)
        held["attempts"] = 2
        with open(poison, "w", encoding="utf-8") as fh:
            json.dump(held, fh)
        got = []
        srv = AdviserServer(env(), memory.Store(self.base), lambda b: got.extend(m.id for m in b), "t", port=0).start()
        try:
            end = time.time() + 5
            while not got and time.time() < end:
                time.sleep(0.02)
            time.sleep(0.2)
            self.assertEqual(got, ["wamid.LOST"])
            self.assertEqual(os.listdir(os.path.join(self.base, ".state", "adviser", "inbox")), [])
        finally:
            srv.stop()

    def test_a_failed_disk_write_does_not_lose_the_message(self):
        # Round 2, #5: hold() failing used to lose the message for good (it was already marked seen).
        class Flaky(memory.Store):
            def hold(self, message):
                raise OSError("disk full")
        got = []
        srv = AdviserServer(env(), Flaky(self.base), lambda b: got.extend(m.id for m in b), "t", port=0).start()
        try:
            self.assertEqual(post(f"http://127.0.0.1:{srv.port}/webhook", webhook(text_msg("wamid.D", "hi"))), 200)
            end = time.time() + 5
            while not got and time.time() < end:
                time.sleep(0.02)
            self.assertEqual(got, ["wamid.D"])
        finally:
            srv.stop()

    def test_a_damaged_inbox_file_does_not_stop_the_start(self):
        import os
        inbox = os.path.join(self.base, ".state", "adviser", "inbox")
        os.makedirs(inbox, exist_ok=True)
        for name, body in (("a.json", '{"message": {"id": "x", "timestamp": "yesterday"}, "attempts": "1"}'),
                           ("b.json", "{not json"), ("c.json", '{"message": {"id": "y", "timestamp": 1e18}}'),
                           ("d.json", '{"message": {"timestamp": %d}}' % time.time()), ("e.json.1234.tmp", "junk")):
            with open(os.path.join(inbox, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        srv = AdviserServer(env(), memory.Store(self.base), lambda b: None, "t", port=0).start()   # must not raise
        srv.stop()
        self.assertEqual(sorted(os.listdir(inbox)), ["c.json", "e.json.1234.tmp"])   # c is "from the future": kept once

    def test_worker_survives_a_base_exception(self):
        import asyncio
        got = []

        def handle(batch):
            got.extend(m.id for m in batch)
            if batch[0].id == "wamid.X1":
                raise asyncio.CancelledError()                          # a BaseException, not an Exception
        srv = AdviserServer(env(), memory.Store(self.base), handle, "t", port=0).start()
        try:
            url = f"http://127.0.0.1:{srv.port}"
            self.assertEqual(post(f"{url}/webhook", webhook(text_msg("wamid.X1", "one"))), 200)
            end = time.time() + 5
            while "wamid.X1" not in got and time.time() < end:
                time.sleep(0.02)
            self.assertEqual(post(f"{url}/webhook", webhook(text_msg("wamid.X2", "two"))), 200)
            while "wamid.X2" not in got and time.time() < end:
                time.sleep(0.02)
            self.assertIn("wamid.X2", got)
            self.assertEqual(json.loads(get(f"{url}/health")[1]), {"ok": True})
        finally:
            srv.stop()

    def test_refuses_to_start_without_secret_or_owner(self):
        with self.assertRaises(ValueError):
            AdviserServer(env(WA_APP_SECRET=""), memory.Store(self.base), print, "t", port=0)
        with self.assertRaises(ValueError):
            AdviserServer(env(WA_TARGET_NUMBER=""), memory.Store(self.base), print, "t", port=0)


class EndToEndTests(TempBrain):
    """Signed webhook in ─▶ real server ─▶ real turn graph ─▶ fake Graph API out.
    Real: HTTP, signature, parsing, download, OGG/Opus encoding, multipart upload, sends.
    Fake: Groq (speech-to-text and the model) and the voice itself (a tone)."""

    def setUp(self):
        super().setUp()
        self.graph = FakeGraph(media=b"OggS-owner-voice")
        e = env(WA_GRAPH_BASE=self.graph.base)
        self.llm = scripted("You stopped at the runbook page in soc-agents. Shall we start it now?")
        svc = turn.Services(
            base_dir=self.base, env=e, client=Client.from_env(e), store=memory.Store(self.base),
            portfolio=brain.Portfolio(self.base), pool=brain.ModelPool([("fake", self.llm)]),
            transcribe=lambda audio, mime, key, hint="": speech.Transcript(
                "where did I leave off on sock agents" if audio == b"OggS-owner-voice" else "?", "en", 2.0),
            render_note=lambda part, voice, rate: speech.render_note(part, voice, rate,
                                                                     synth=lambda t, v, r: tone(1.5, fmt="MP3")))
        graph = turn.build_turn(svc)
        self.server = AdviserServer(e, svc.store, lambda b: turn.handle(graph, b, OWNER), "tok", port=0).start()
        self.url = f"http://127.0.0.1:{self.server.port}/webhook"

    def tearDown(self):
        self.server.stop()
        self.graph.close()
        super().tearDown()

    def test_voice_note_round_trip(self):
        self.assertEqual(post(self.url, webhook(voice_msg("wamid.V1", "media-42"))), 200)
        self.assertTrue(self.graph.wait_for(lambda g: any(p.get("type") == "audio" for p in g.sent)),
                        f"no voice reply; sent={self.graph.sent}")
        read, reply = self.graph.sent[0], self.graph.sent[-1]
        self.assertEqual(read, {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.V1",
                                "typing_indicator": {"type": "text"}})
        self.assertEqual(reply["to"], OWNER)
        self.assertEqual(reply["audio"], {"id": "up-1", "voice": True})
        paths = [r[1] for r in self.graph.requests]
        self.assertIn("/v26.0/media-42", paths)
        self.assertIn("/files/media-42", paths)
        ctype, body = self.graph.uploads[0]
        ogg = body[body.index(b"OggS"):body.rindex(b"\r\n--")]
        info = sf.info(io.BytesIO(ogg))
        self.assertEqual((info.format, info.subtype, info.channels), ("OGG", "OPUS", 1))
        self.assertLess(len(ogg), speech.VOICE_MAX_BYTES)
        self.assertIn(b'name="type"\r\n\r\naudio/ogg', body)
        self.assertTrue(self.llm.seen[0][-1].content.startswith("where did I leave off on sock agents\n\n[This answer"))

    def test_text_round_trip(self):
        self.assertEqual(post(self.url, webhook(text_msg("wamid.T1", "what next on soc-agents?"))), 200)
        self.assertTrue(self.graph.wait_for(lambda g: any(p.get("type") == "text" for p in g.sent)))
        self.assertEqual(self.graph.sent[-1]["text"]["body"],
                         "You stopped at the runbook page in soc-agents. Shall we start it now?")
        self.assertEqual(self.graph.uploads, [])


class RegistrationTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.graph = FakeGraph()
        self.server = AdviserServer(env(), memory.Store(self.base), lambda b: None, "verify-xyz", port=0).start()
        self.callback = f"http://127.0.0.1:{self.server.port}/webhook"

    def tearDown(self):
        self.server.stop()
        self.graph.close()
        super().tearDown()

    def test_registers_app_webhook_and_waba_subscription(self):
        aid = retry_reset(tunnel.register, env(WA_GRAPH_BASE=self.graph.base), self.callback, "verify-xyz")
        self.assertEqual(aid, "999000")                                   # read from the token
        posts = [(r[1], r[2], r[3]) for r in self.graph.requests if r[0] == "POST"]
        subs = [p for p in posts if p[0].endswith("/subscriptions")]       # >1 only if a reset forced a retry
        sub_path, sub_auth, sub_body = subs[-1]
        form = dict(__import__("urllib.parse").parse.parse_qsl(sub_body.decode()))
        self.assertEqual(sub_path, "/v26.0/999000/subscriptions")
        self.assertIsNone(sub_auth)
        self.assertEqual({k: form[k] for k in ("object", "callback_url", "verify_token", "fields", "access_token")},
                         {"object": "whatsapp_business_account", "callback_url": self.callback,
                          "verify_token": "verify-xyz", "fields": "messages", "access_token": "999000|app-secret-123"})
        waba = [p[:2] for p in posts if p[0].endswith("/subscribed_apps")]
        self.assertEqual(waba, [("/v26.0/444555666/subscribed_apps", "Bearer sys-token")])
        self.assertEqual(posts[-1][0], "/v26.0/444555666/subscribed_apps")      # only after the webhook is set

    def test_wrong_verify_token_fails_registration(self):
        with self.assertRaises(tunnel.RegistrationError) as ctx:
            retry_reset(tunnel.register, env(WA_GRAPH_BASE=self.graph.base, WA_APP_ID="42"), self.callback,
                        "not-the-token")
        self.assertIn("HTTP 400", str(ctx.exception))     # plus Meta's code 2200 when the body arrives


class FakeProc:
    def __init__(self, lives=True):
        self.returncode = None if lives else 1
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.returncode = -9


class TunnelTests(unittest.TestCase):
    def test_quick_tunnel_reads_hostname_from_metrics(self):
        started, answers = [], iter([(200, b'{"hostname":""}'), (200, b'{"hostname":"abc-def.trycloudflare.com"}')])

        def popen(args, **kw):
            started.append(args)
            return FakeProc()
        qt = tunnel.QuickTunnel("cloudflared.exe", 8765, "C:/tmp/cf.log", popen=popen,
                                get=lambda url, timeout: next(answers), sleep=lambda s: None)
        self.assertEqual(qt.start(), "https://abc-def.trycloudflare.com")
        self.assertIn("--url", started[0])
        self.assertEqual(started[0][started[0].index("--url") + 1], "http://127.0.0.1:8765")
        qt.stop()
        self.assertFalse(qt.alive())

    def test_leftover_cloudflared_is_stopped_only_if_it_is_ours(self):
        import os
        import tempfile
        folder = tempfile.mkdtemp(prefix="sb-cf-")
        exe = os.path.join(folder, "cloudflared.exe")
        mine = f'"{exe}" tunnel --no-autoupdate --url http://127.0.0.1:8765 --metrics 127.0.0.1:5000'
        calls = []

        def run(args, **kw):
            calls.append(args[0])

            class R:
                stdout = cmdline
            return R()

        for cmdline, expected in (
                (mine, ["powershell", "taskkill"]),                                            # our leftover
                (mine.replace("8765", "9999"), ["powershell"]),                                # another port
                (mine.replace("8765", "87650"), ["powershell"]),                               # a longer port
                (r'"C:\Users\PC\Downloads\shoe-agent\tools\cloudflared.exe" tunnel --url http://127.0.0.1:8765',
                 ["powershell"]),                                                              # another program's
                ("notepad.exe", ["powershell"]),                                               # a reused PID
                ("", ["powershell"])):                                                         # already gone
            calls.clear()
            qt = tunnel.QuickTunnel(exe, 8765, os.path.join(folder, "cf.log"), run=run)
            self.assertTrue(qt.pid_path.endswith("cloudflared-8765.pid"))
            with open(qt.pid_path, "w") as fh:
                fh.write("4242")
            qt._kill_leftover()
            self.assertEqual(calls, expected, cmdline)
            self.assertFalse(os.path.exists(qt.pid_path))

        class P(FakeProc):
            pid = 777
        qt = tunnel.QuickTunnel(exe, 8765, os.path.join(folder, "cf.log"), popen=lambda a, **k: P(),
                                get=lambda u, t: (200, b'{"hostname":"x.trycloudflare.com"}'), run=run)
        qt.start()
        with open(qt.pid_path) as fh:
            self.assertEqual(fh.read(), "777")
        self.assertTrue(qt.ready())                           # /ready answers 200 in this fake
        qt.stop()
        self.assertFalse(os.path.exists(qt.pid_path))
        self.assertFalse(qt.ready())

    def test_quick_tunnel_that_dies_raises(self):
        qt = tunnel.QuickTunnel("cloudflared.exe", 1, "C:/tmp/cf.log", popen=lambda a, **k: FakeProc(lives=False),
                                get=lambda u, t: (500, b""), sleep=lambda s: None)
        with self.assertRaises(RuntimeError):
            qt.start()

    class FakeTunnel:
        def __init__(self, ready_after=0):
            self.n, self.proc_alive, self.ready_after, self.checks = 0, True, ready_after, 0

        def start(self):
            self.n += 1
            self.proc_alive, self.checks = True, 0
            return f"https://t{self.n}.trycloudflare.com"

        def alive(self):
            return self.proc_alive

        def ready(self):
            self.checks += 1
            return self.proc_alive and self.checks > self.ready_after

        def stop(self):
            self.proc_alive = False

    def endpoint(self, t, register, on_url=lambda u: None, stop_when=lambda: False, crash_when=lambda: False,
                 tries=tunnel.REGISTER_TRIES):
        clock = {"t": 0.0}

        def sleep(s):
            clock["t"] += s
            if crash_when():
                t.proc_alive = False
            if stop_when():
                ep.stopping.set()
        ep = tunnel.PublicEndpoint(t, register, on_url=on_url, clock=lambda: clock["t"], sleep=sleep,
                                   register_tries=tries)
        return ep

    def test_supervisor_registers_then_restarts_when_cloudflared_stops(self):
        t, registered, urls = self.FakeTunnel(ready_after=2), [], []
        ep = self.endpoint(t, registered.append, urls.append, stop_when=lambda: len(registered) >= 2,
                           crash_when=lambda: len(registered) == 1 and t.n == 1)
        ep.run()
        self.assertEqual(registered, ["https://t1.trycloudflare.com/webhook", "https://t2.trycloudflare.com/webhook"])
        self.assertEqual(urls, ["https://t1.trycloudflare.com", "https://t2.trycloudflare.com"])
        self.assertEqual(ep.url, "https://t2.trycloudflare.com")
        self.assertEqual(ep.last_error, "")                  # healthy again after the restart

    def test_meta_verification_is_retried_on_the_same_tunnel(self):
        # A brand-new hostname may not resolve for Meta yet: retry registration, don't restart the tunnel.
        t, attempts = self.FakeTunnel(), []

        def register(cb):
            attempts.append(cb)
            if len(attempts) < 3:
                raise tunnel.RegistrationError("code 2200: Callback verification failed")
        ep = self.endpoint(t, register, stop_when=lambda: len(attempts) >= 3 and ep.registered_at > 0)
        ep.run()
        self.assertEqual(attempts, ["https://t1.trycloudflare.com/webhook"] * 3)
        self.assertEqual(t.n, 1)
        self.assertEqual(ep.url, "https://t1.trycloudflare.com")

    def test_registration_that_keeps_failing_starts_a_new_tunnel(self):
        t, attempts = self.FakeTunnel(), []

        def register(cb):
            attempts.append(cb)
            raise tunnel.RegistrationError("code 190: bad app secret")
        ep = self.endpoint(t, register, tries=2, stop_when=lambda: t.n >= 2 and len(attempts) >= 4)
        ep.run()
        self.assertEqual(attempts[:2], ["https://t1.trycloudflare.com/webhook"] * 2)
        self.assertIn("code 190", ep.last_error)
        self.assertEqual(ep.url, "")

    def test_no_register_mode_never_calls_meta(self):
        t, urls = self.FakeTunnel(), []
        ep = self.endpoint(t, None, urls.append, stop_when=lambda: bool(urls))
        ep.run()
        self.assertEqual(urls, ["https://t1.trycloudflare.com"])
        self.assertEqual(ep.last_error, "")

    def test_tunnel_that_never_connects_is_not_registered(self):
        t, registered = self.FakeTunnel(ready_after=10**9), []
        ep = self.endpoint(t, registered.append, stop_when=lambda: t.n >= 1 and bool(ep.last_error))
        ep.run()
        self.assertEqual(registered, [])
        self.assertIn("never connected", ep.last_error)


if __name__ == "__main__":
    unittest.main()
