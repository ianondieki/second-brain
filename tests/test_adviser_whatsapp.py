"""WhatsApp two-way layer: signature, verification, payload parsing, builders, media client.

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_whatsapp -v
"""
import json
import unittest

from adviser import whatsapp
from reminder.notify import DeliveryError
from tests.adviser_fakes import OWNER, PNID, SECRET, FakeGraph, sign, text_msg, voice_msg, webhook


class SignatureTests(unittest.TestCase):
    body = b'{"object":"whatsapp_business_account"}'

    def test_valid_signature(self):
        self.assertTrue(whatsapp.verify_signature(SECRET, self.body, sign(self.body)))
        self.assertTrue(whatsapp.verify_signature(SECRET, self.body, sign(self.body).upper().replace("SHA256", "sha256")))

    def test_rejects_tampering_wrong_secret_and_missing(self):
        self.assertFalse(whatsapp.verify_signature(SECRET, self.body + b" ", sign(self.body)))
        self.assertFalse(whatsapp.verify_signature("other", self.body, sign(self.body)))
        self.assertFalse(whatsapp.verify_signature(SECRET, self.body, None))
        self.assertFalse(whatsapp.verify_signature(SECRET, self.body, ""))
        self.assertFalse(whatsapp.verify_signature(SECRET, self.body, "sha1=" + sign(self.body)[7:]))
        self.assertFalse(whatsapp.verify_signature("", self.body, sign(self.body, "")))
        self.assertFalse(whatsapp.verify_signature(SECRET, self.body, "sha256=é" * 3))   # L3: no crash


class ChallengeTests(unittest.TestCase):
    def test_echoes_challenge_only_for_the_right_token(self):
        q = {"hub.mode": ["subscribe"], "hub.verify_token": ["tok"], "hub.challenge": ["1158201444"]}
        self.assertEqual(whatsapp.verify_challenge(q, "tok"), "1158201444")
        self.assertIsNone(whatsapp.verify_challenge({**q, "hub.verify_token": ["nope"]}, "tok"))
        self.assertIsNone(whatsapp.verify_challenge({**q, "hub.mode": ["unsubscribe"]}, "tok"))
        self.assertIsNone(whatsapp.verify_challenge(q, ""))
        self.assertIsNone(whatsapp.verify_challenge({**q, "hub.challenge": ["<script>"]}, "tok"))


class ParseTests(unittest.TestCase):
    def test_text_with_reply_context_and_name(self):
        msgs, statuses = whatsapp.parse_webhook(webhook(text_msg("wamid.1", "hi there", reply_to="wamid.rem")))
        self.assertEqual(statuses, [])
        m = msgs[0]
        self.assertEqual((m.kind, m.text, m.sender, m.reply_to, m.name, m.phone_number_id),
                         ("text", "hi there", OWNER, "wamid.rem", "Owner", PNID))

    def test_voice_note_and_audio_file(self):
        msgs, _ = whatsapp.parse_webhook(webhook(voice_msg("wamid.2"), voice_msg("wamid.3", "m3", voice=False)))
        self.assertEqual([(m.kind, m.media_id, m.mime) for m in msgs],
                         [("voice", "media-1", "audio/ogg; codecs=opus"), ("audio", "m3", "audio/ogg; codecs=opus")])

    def test_buttons_reactions_and_other_types(self):
        base = {"from": OWNER, "timestamp": "1"}
        msgs, _ = whatsapp.parse_webhook(webhook(
            {**base, "id": "b", "type": "button", "button": {"text": "Snooze", "payload": "p"}},
            {**base, "id": "i", "type": "interactive", "interactive": {"button_reply": {"id": "x", "title": "Yes"}}},
            {**base, "id": "r", "type": "reaction", "reaction": {"emoji": "\U0001F44D", "message_id": "w"}},
            {**base, "id": "img", "type": "image", "image": {"id": "9"}},
            {**base, "id": "empty", "type": "text", "text": {"body": "   "}},
            {**base, "id": "noaudio", "type": "audio", "audio": {}}))
        self.assertEqual([(m.id, m.kind, m.text) for m in msgs],
                         [("b", "text", "Snooze"), ("i", "text", "Yes"), ("r", "reaction", "\U0001F44D"),
                          ("img", "other", ""), ("empty", "other", "   "), ("noaudio", "other", "")])

    def test_status_updates_are_not_messages(self):
        payload = webhook(statuses=[{"id": "wamid.out", "status": "delivered", "recipient_id": OWNER}])
        msgs, statuses = whatsapp.parse_webhook(payload)
        self.assertEqual(msgs, [])
        self.assertEqual(statuses[0]["status"], "delivered")

    def test_odd_shapes_never_raise(self):
        for bad in (None, [], "x", {"entry": None}, {"entry": ["x"]}, {"entry": [{"changes": [None, {"field": "other"}]}]},
                    {"entry": [{"changes": [{"field": "messages", "value": {"messages": [None, {"id": "x"}, 5]}}]}]}):
            self.assertEqual(whatsapp.parse_webhook(bad), ([], []))

    def test_one_odd_item_does_not_lose_the_others(self):
        # The review's L4: shapes that used to raise, next to a good message.
        good = text_msg("wamid.ok", "still here")
        payload = webhook(good, {"from": OWNER, "id": "x", "type": "interactive", "interactive": {"button_reply": "x"}})
        payload["entry"][0]["changes"][0]["value"]["contacts"] = [{"profile": "x", "wa_id": OWNER}]
        payload["entry"].append({"changes": 5})
        msgs, _ = whatsapp.parse_webhook(payload)
        self.assertEqual([m.id for m in msgs if m.kind == "text"], ["wamid.ok"])


class BuilderTests(unittest.TestCase):
    def test_voice_note_payload(self):
        p = whatsapp.build_voice("+254 700 000 001", "m1")
        self.assertEqual(p["to"], OWNER)
        self.assertEqual(p["audio"], {"id": "m1", "voice": True})
        self.assertEqual(p["type"], "audio")

    def test_read_with_typing(self):
        self.assertEqual(whatsapp.build_read("wamid.9")["typing_indicator"], {"type": "text"})
        self.assertNotIn("typing_indicator", whatsapp.build_read("wamid.9", typing=False))

    def test_text_is_capped(self):
        body = whatsapp.build_text(OWNER, "x" * 5000)["text"]["body"]
        self.assertEqual(len(body), whatsapp.TEXT_MAX)
        self.assertEqual(whatsapp.build_text(OWNER, "  ")["text"]["body"], "…")

    def test_markdown_becomes_whatsapp_formatting(self):
        md = ("**What it is**  \nAether is an assistant.\n\n\n### Next step\n* Open `README.md`\n"
              "+ Read [the docs](https://x.dev/a) and test_remind.py\n***Done***")
        self.assertEqual(whatsapp.for_whatsapp(md),
                         "*What it is*\nAether is an assistant.\n\n*Next step*\n- Open `README.md`\n"
                         "- Read the docs (https://x.dev/a) and test_remind.py\n*Done*")
        self.assertEqual(whatsapp.for_whatsapp("*already* _fine_ ~ok~"), "*already* _fine_ ~ok~")
        code = "**Run it:**\n```\ndef f(**kwargs):\n    return __name__\n# heading?\n```"
        self.assertEqual(whatsapp.for_whatsapp(code),
                         "*Run it:*\n```\ndef f(**kwargs):\n    return __name__\n# heading?\n```")

    def test_code_and_paths_outside_fences_are_not_mangled(self):
        # The review's M3.
        for keep in ("Edit adviser/__init__.py first.", "if __name__ == '__main__': main()", "call f(*args, **kwargs)",
                     "2**10 is 1024", "#1 priority is the scheduler", "Use `**kwargs` and `__init__`",
                     "C# and F# are fine"):
            self.assertEqual(whatsapp.for_whatsapp(keep), keep, keep)
        self.assertEqual(whatsapp.for_whatsapp("## Learning C#"), "*Learning C#*")
        # Round 2, #7: bold around inline code, repeated powers, globs, an unclosed fence
        self.assertEqual(whatsapp.for_whatsapp("**Run `git push` today**"), "*Run `git push` today*")
        self.assertEqual(whatsapp.for_whatsapp("Open **`README.md`**"), "Open *`README.md`*")
        for keep in ("2**10 and 2**20", "match **/*.py files", "```\n# a comment\n**x**"):
            self.assertEqual(whatsapp.for_whatsapp(keep), keep, keep)
        self.assertEqual(whatsapp.for_whatsapp("## Title ##"), "*Title*")

    def test_multipart_carries_fields_and_file(self):
        body, ctype = whatsapp.multipart({"type": "audio/ogg"}, {"file": ("r.ogg", "audio/ogg", b"OggS\x00")})
        boundary = ctype.split("boundary=")[1]
        self.assertIn(f"--{boundary}--".encode(), body)
        self.assertIn(b'name="type"\r\n\r\naudio/ogg\r\n', body)
        self.assertIn(b'filename="r.ogg"\r\nContent-Type: audio/ogg\r\n\r\nOggS\x00\r\n', body)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.graph = FakeGraph(media=b"OggS-voice")
        self.client = whatsapp.Client("sys-token", PNID, base=self.graph.base)

    def tearDown(self):
        self.graph.close()

    def test_download_follows_url_with_token(self):
        data, mime = self.client.download("media-7")
        self.assertEqual((data, mime), (b"OggS-voice", "audio/ogg; codecs=opus"))
        auth = [r[2] for r in self.graph.requests]
        self.assertEqual(auth, ["Bearer sys-token", "Bearer sys-token"])

    def test_upload_then_voice_send(self):
        mid = self.client.send_voice(OWNER, b"OggS1234")
        self.assertEqual(mid, "wamid.out1")
        ctype, body = self.graph.uploads[0]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(b"OggS1234", body)
        self.assertIn(b'name="messaging_product"\r\n\r\nwhatsapp', body)
        self.assertEqual(self.graph.sent[0]["audio"], {"id": "up-1", "voice": True})

    def test_mark_read_and_text(self):
        self.client.mark_read("wamid.in")
        self.client.send_text(OWNER, "hello")
        self.assertEqual(self.graph.sent[0]["status"], "read")
        self.assertEqual(self.graph.sent[1]["text"]["body"], "hello")

    def test_dropped_connection_while_reading_an_error_is_still_a_delivery_error(self):
        import urllib.error

        class Dropped:
            def read(self, *a):
                raise ConnectionResetError(10054, "forcibly closed")

            def close(self):
                pass
        exc = urllib.error.HTTPError("https://graph.facebook.com/x", 503, "busy", {}, Dropped())
        self.assertEqual(whatsapp.error_body(exc), "")
        err = whatsapp._meta_error(exc)
        self.assertIsInstance(err, DeliveryError)
        self.assertTrue(err.transient)
        self.assertIn("HTTP 503", str(err))

    def test_media_urls_must_be_meta_hosts(self):
        c = whatsapp.Client("t", PNID)
        self.assertTrue(c._trusted("https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1"))
        self.assertFalse(c._trusted("http://lookaside.fbsbx.com/x"))
        self.assertFalse(c._trusted("https://evil.example/fbsbx.com"))
        self.assertFalse(c._trusted("https://fbsbx.com.evil.example/x"))

    def test_meta_errors_become_delivery_errors(self):
        c = whatsapp.Client("t", PNID, base=self.graph.base)
        with self.assertRaises(DeliveryError) as ctx:
            c._json(__import__("urllib.request").request.Request(f"{self.graph.base}/v26.0/nowhere", method="POST",
                                                                 data=json.dumps({}).encode()))
        self.assertIn("code 100", str(ctx.exception))
        self.assertFalse(ctx.exception.transient)


if __name__ == "__main__":
    unittest.main()
