"""Speech: text for the ear, OGG/Opus encoding, voice-note splitting, transcription (no network).

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_speech -v
"""
import io
import json
import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler

import soundfile as sf

from adviser import speech
from adviser.server import ExclusiveHTTPServer
from tests.adviser_fakes import LIVE_WRAPPED_REPLY, tone


class SpeakableTests(unittest.TestCase):
    def test_strips_marks_links_code_and_emoji(self):
        s = speech.speakable("## Next step\n- *Fix* the `scheduler` in app.py \U0001F680\n"
                             "- Read https://x.com/a and test_remind.py\n```py\nprint(1)\n```\n_Done_")
        self.assertEqual(s, "Next step. Fix the scheduler in app.py. Read the link and test_remind.py. Done.")

    def test_keeps_punctuation_and_numbers(self):
        self.assertEqual(speech.speakable("1. First, commit.\n2) Then push!"), "First, commit. Then push!")
        self.assertEqual(speech.speakable(""), "")


class SplitTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(speech.split_for_voice("One. Two."), ["One. Two."])
        self.assertEqual(speech.split_for_voice("  "), [])

    def test_long_text_splits_on_sentences_under_the_limit(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(100))
        chunks = speech.split_for_voice(text, 200)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        self.assertEqual(" ".join(chunks), text)
        self.assertTrue(all(c.endswith(".") for c in chunks))

    def test_one_huge_sentence_is_cut(self):
        chunks = speech.split_for_voice("word, " * 300, 150)
        self.assertTrue(all(len(c) <= 151 for c in chunks))
        self.assertGreater(len(chunks), 5)


class CodeTests(unittest.TestCase):
    def test_code_lines_and_fences_come_out_of_speech(self):
        prose, code = speech.separate_code(LIVE_WRAPPED_REPLY.replace("[[", "\n").replace("]]", ""))
        self.assertNotIn("import", prose)
        self.assertNotIn("scheduler.start", prose)
        for line in ("pip install APScheduler==3.10.4", "from apscheduler.schedulers.blocking import BlockingScheduler",
                     'tz = pytz.timezone("Africa/Nairobi")', "def send_brief():",
                     '    notifier.show_toast("Morning Brief", brief, duration=10)', "scheduler.start()"):
            self.assertIn(line, code)
        self.assertIn("Set up a tiny scheduler first.", prose)

    def test_prose_is_left_alone(self):
        text = ("Git is how you save versions. Then run the tests, and push.\n"
                "Your app.py file has the scheduler. It returns early when the config is empty.")
        self.assertEqual(speech.separate_code(text), (text, ""))

    def test_fenced_blocks(self):
        prose, code = speech.separate_code("Run this:\n```bash\ngit add -A\ngit commit -m wip\n```\nThen push.")
        self.assertEqual((prose, code), ("Run this:\n\nThen push.", "git add -A\ngit commit -m wip"))


class PlanTests(unittest.TestCase):
    def test_short_first_note_then_even_notes(self):
        text = " ".join(f"Sentence {i} explains one more detail of the project." for i in range(40))
        parts = speech.plan_voice(text)
        self.assertLessEqual(len(parts[0]), speech.FIRST_CHARS)
        self.assertEqual(" ".join(parts), text)
        rest = [len(p) for p in parts[1:]]
        self.assertGreaterEqual(len(rest), 2)
        self.assertLess(max(rest) - min(rest), 250)
        self.assertTrue(all(n <= speech.CHUNK_CHARS + 250 for n in rest))

    def test_short_answers_are_one_note(self):
        self.assertEqual(speech.plan_voice("Yes, push it now."), ["Yes, push it now."])
        self.assertEqual(speech.plan_voice("```\nonly code\n```"), [])


class EncodeTests(unittest.TestCase):
    def check_voice_note(self, ogg: bytes):
        self.assertEqual(ogg[:4], b"OggS")
        self.assertIn(b"OpusHead", ogg[:200])
        info = sf.info(io.BytesIO(ogg))
        self.assertEqual((info.format, info.subtype, info.channels), ("OGG", "OPUS", 1))
        self.assertIn(info.samplerate, speech.OPUS_RATES)
        return info

    def test_wav_and_mp3_become_mono_opus(self):
        self.check_voice_note(speech.to_ogg_opus(tone(0.5)))
        info = self.check_voice_note(speech.to_ogg_opus(tone(1.0, fmt="MP3")))
        self.assertAlmostEqual(info.duration, 1.0, delta=0.15)

    def test_stereo_and_odd_rates_are_converted(self):
        import numpy as np
        buf = io.BytesIO()
        sf.write(buf, np.zeros((22050, 2), dtype="float32"), 22050, format="WAV")
        info = self.check_voice_note(speech.to_ogg_opus(buf.getvalue()))
        self.assertEqual(info.samplerate, 24000)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.1)

    def test_garbage_raises_speech_error(self):
        with self.assertRaises(speech.SpeechError):
            speech.to_ogg_opus(b"not audio at all")

    def test_voice_notes_speak_clean_text_and_split_big_notes(self):
        said = []

        def synth(text, voice, rate):
            said.append((text, voice, rate))
            return tone(0.3)
        notes = speech.voice_notes("*Hello* there.", voice="v1", rate="+5%", synth=synth)
        self.assertEqual(said, [("Hello there.", "v1", "+5%")])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0][:4], b"OggS")

        said.clear()
        old = speech.VOICE_MAX_BYTES
        speech.VOICE_MAX_BYTES = 10                       # every note is "too big": long text must split
        try:
            text = " ".join(f"This is sentence {i} of a long answer." for i in range(20))
            notes = speech.voice_notes(text, synth=synth, limit=2000)
        finally:
            speech.VOICE_MAX_BYTES = old
        # Too-big parts are halved until they are 200 characters or less, then kept as they are.
        kept = [t for t, _, _ in said if len(t) <= 200]
        self.assertGreater(len(notes), 1)
        self.assertEqual(len(kept), len(notes))
        self.assertEqual(" ".join(kept), speech.speakable(text))

    def test_nothing_to_say(self):
        with self.assertRaises(speech.SpeechError):
            speech.voice_notes("```\ncode only\n```", synth=lambda *a: tone(0.1))


class EdgeTlsTests(unittest.TestCase):
    def test_swaps_certifi_context_for_windows_store(self):
        import edge_tts.communicate as comm
        original = comm._SSL_CTX
        try:
            ctx = speech._edge_tls()
            self.assertIs(comm._SSL_CTX, ctx)
            self.assertFalse(ctx.verify_flags & ssl.VERIFY_X509_STRICT)
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        finally:
            comm._SSL_CTX = original


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.got = []
        self.status, self.reply = 200, {"text": " Where did I leave off? ", "language": "english", "duration": 2.5}
        test = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                test.got.append((self.headers.get("Authorization"), self.headers.get("Content-Type"), body))
                out = json.dumps(test.reply).encode()
                self.send_response(test.status)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = ExclusiveHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/stt"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_sends_ogg_with_hint_and_reads_language(self):
        t = speech.transcribe(b"OggS-data", "audio/ogg; codecs=opus", "gsk-1", hint="Projects: soc-agents",
                              url=self.url)
        self.assertEqual((t.text, t.language, t.seconds), ("Where did I leave off?", "en", 2.5))
        auth, ctype, body = self.got[0]
        self.assertEqual(auth, "Bearer gsk-1")
        self.assertTrue(ctype.startswith("multipart/form-data"))
        for part in (b'name="model"\r\n\r\nwhisper-large-v3-turbo', b'name="prompt"\r\n\r\nProjects: soc-agents',
                     b'filename="voice.ogg"', b"OggS-data", b'name="response_format"\r\n\r\nverbose_json'):
            self.assertIn(part, body)

    def test_rate_limit_is_transient(self):
        self.status, self.reply = 429, {"error": {"message": "slow down"}}
        with self.assertRaises(speech.SpeechError) as ctx:
            speech.transcribe(b"x", "audio/ogg", "k", url=self.url)
        self.assertTrue(ctx.exception.transient)

    def test_refuses_unsupported_types_and_missing_key(self):
        with self.assertRaises(speech.SpeechError):
            speech.transcribe(b"x", "audio/amr", "k", url=self.url)
        with self.assertRaises(speech.SpeechError):
            speech.transcribe(b"x", "audio/ogg", "", url=self.url)
        with self.assertRaises(speech.SpeechError):
            speech.transcribe(b"", "audio/ogg", "k", url=self.url)
        self.assertEqual(self.got, [])


if __name__ == "__main__":
    unittest.main()
