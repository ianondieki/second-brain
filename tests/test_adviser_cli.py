"""The command line itself: console encoding and the setup check. No network, nothing sent.

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_cli -v
"""
import io
import sys
import time
import unittest
from unittest import mock

from adviser import __main__ as cli

# What a model actually writes: a narrow no-break space, an en dash, an ellipsis and an emoji.
# A cp1252 console can encode none of them.
MODEL_TYPOGRAPHY = "15 minutes – soc-agents… \U0001F4CC"


def cp1252_stream():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")


class ConsoleEncodingTests(unittest.TestCase):
    """Regression: `chat` answered in 2.7s and then lost the whole reply to UnicodeEncodeError,
    because print() went to a cp1252 console."""

    def test_widen_console_switches_both_streams_to_utf8(self):
        out, err = cp1252_stream(), cp1252_stream()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            cli.widen_console()
            print(MODEL_TYPOGRAPHY)                      # would raise UnicodeEncodeError before
            self.assertEqual((sys.stdout.encoding, sys.stderr.encoding), ("utf-8", "utf-8"))
        out.flush()
        self.assertIn(MODEL_TYPOGRAPHY, out.buffer.getvalue().decode("utf-8"))

    def test_widen_console_survives_streams_it_cannot_change(self):
        class Closed:
            encoding = "cp1252"

            def reconfigure(self, **kw):
                raise ValueError("I/O operation on closed file")

        for stream in (None, object(), Closed()):        # pythonw.exe, an odd wrapper, a closed stream
            with mock.patch.object(sys, "stdout", stream), mock.patch.object(sys, "stderr", stream):
                cli.widen_console()                      # must not raise

    def test_main_widens_the_console_before_the_command_prints(self):
        out = cp1252_stream()
        seen = {}

        def fake_check(env, out=print):
            seen["encoding"] = sys.stdout.encoding
            out(MODEL_TYPOGRAPHY)
            return 0

        with mock.patch.object(sys, "stdout", out), mock.patch.object(cli, "check", fake_check), \
                mock.patch.object(cli, "setup_logging"), \
                mock.patch.object(cli.remind, "load_env", return_value={}):
            self.assertEqual(cli.main(["check"]), 0)
        self.assertEqual(seen["encoding"], "utf-8")
        out.flush()
        self.assertIn(MODEL_TYPOGRAPHY, out.buffer.getvalue().decode("utf-8"))


class BriefCommandTests(unittest.TestCase):
    """`adviser brief` says today's check-in on demand; --dry-run must never send."""

    def run_brief(self, dry_run, tick="spoken", last_inbound=0.0, script_text="Good morning."):
        lines = []
        services = mock.MagicMock()
        services.store.last_inbound.return_value = last_inbound
        with mock.patch.object(cli, "build_services", return_value=services), \
                mock.patch.object(cli.memory, "load_briefing", return_value={"sent_at": "x"}), \
                mock.patch.object(cli.briefing, "script", return_value=script_text), \
                mock.patch.object(cli.briefing.Speaker, "tick", return_value=tick) as ticked, \
                mock.patch.object(cli.briefing.Speaker, "window_open", return_value=bool(last_inbound)):
            code = cli.brief(mock.MagicMock(dry_run=dry_run), {"WA_TARGET_NUMBER": "254700000512"}, lines.append)
        return code, "\n".join(lines), ticked

    def test_dry_run_prints_the_words_and_sends_nothing(self):
        code, out, ticked = self.run_brief(True, script_text="Good morning. One project needs you today: app.")
        self.assertEqual(code, 0)
        self.assertIn("One project needs you today: app.", out)
        self.assertIn("WhatsApp window: closed", out)
        self.assertIn("goes out the moment you write", out)
        ticked.assert_not_called()                                 # nothing may be sent by a dry run

    def test_dry_run_says_when_the_window_is_open(self):
        _, out, _ = self.run_brief(True, last_inbound=time.time() - 60)
        self.assertIn("WhatsApp window: open", out)
        self.assertNotIn("never", out)

    def test_dry_run_explains_an_empty_check_in(self):
        _, out, _ = self.run_brief(True, script_text="")
        self.assertIn("Nothing to say", out)

    def test_it_reports_each_outcome_in_plain_words(self):
        for what, expect in (("spoken", "Spoken on WhatsApp."), ("waiting", "WhatsApp allows a voice note"),
                             ("busy", "already dealing with it"), ("nothing new", "already been spoken"),
                             ("text mode", "/text"), ("off", "ADVISER_DAILY_VOICE"),
                             ("failed", "adviser.log"), ("stale", "too old")):
            code, out, ticked = self.run_brief(False, tick=what)
            self.assertEqual(code, 0, what)
            self.assertIn(expect, out, what)
            ticked.assert_called_once()


class CheckTests(unittest.TestCase):
    # Values that cannot appear by accident in the check's own wording, so "never echo a secret" means it.
    FULL = {"WA_ACCESS_TOKEN": "EAAGzzq7fakeaccesstoken", "WA_PHONE_NUMBER_ID": "1", "WA_BUSINESS_ACCOUNT_ID": "2",
            "GROQ_API_KEY": "gsk_zzq7fakegroqkey", "WA_TARGET_NUMBER": "254700000512",
            "WA_APP_SECRET": "a1b2c3d4e5f60718293a4b5c6d7e8f90"}

    def run_check(self, env):
        lines = []
        return cli.check(dict(env), lines.append), lines

    def test_a_missing_app_secret_is_the_one_thing_that_blocks_the_start(self):
        env = {k: v for k, v in self.FULL.items() if k != "WA_APP_SECRET"}
        code, lines = self.run_check(env)
        self.assertEqual(code, 1)
        joined = "\n".join(lines)
        self.assertIn("[ ] WA_APP_SECRET", joined)
        self.assertIn("App settings > Basic > App secret", joined)
        self.assertIn("Not ready yet", joined)
        for name in ("WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "GROQ_API_KEY"):
            self.assertIn(f"[x] {name}", joined)

    def test_everything_set_says_ready_and_hides_the_owners_number(self):
        code, lines = self.run_check(self.FULL)
        joined = "\n".join(lines)
        self.assertEqual(code, 0, joined)
        self.assertIn("Ready: run", joined)
        self.assertIn("[x] WA_APP_SECRET", joined)
        self.assertIn("512", joined)                                  # the last digits, to confirm the number
        self.assertNotIn(self.FULL["WA_TARGET_NUMBER"], joined)       # but never the whole number
        for secret in (self.FULL["WA_APP_SECRET"], self.FULL["WA_ACCESS_TOKEN"], self.FULL["GROQ_API_KEY"]):
            self.assertNotIn(secret, joined)                          # and never a secret's value

    def test_a_secret_of_the_wrong_shape_is_refused_with_its_length(self):
        """A pasted-wrong secret used to show as a tick here, and the only symptom was Meta
        answering "Invalid OAuth access token signature", which names the token, not the secret."""
        for bad, why in (("a1b2c3", "too short"), ("A1B2C3D4E5F60718293A4B5C6D7E8F90", "upper case"),
                         ("a1b2c3d4e5f60718293a4b5c6d7e8f90ff", "too long"),
                         ("g1b2c3d4e5f60718293a4b5c6d7e8f90", "not hex"),
                         ("a1b2c3d4e5f60718293a4b5c6d7e8f90 ", "trailing space")):
            code, lines = self.run_check({**self.FULL, "WA_APP_SECRET": bad})
            joined = "\n".join(lines)
            self.assertEqual(code, 1, why)
            self.assertIn("[ ] WA_APP_SECRET", joined, why)
            self.assertIn("does not look like an app secret", joined, why)
            self.assertIn(f"{len(bad)} characters", joined, why)
            self.assertIn("exactly 32", joined, why)
            self.assertNotIn(bad, joined, why)                       # never echo it back
        self.assertEqual(self.run_check(self.FULL)[0], 0)             # and a real one still passes

    def test_each_missing_key_is_named(self):
        for key in ("WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "WA_BUSINESS_ACCOUNT_ID", "GROQ_API_KEY"):
            env = {k: v for k, v in self.FULL.items() if k != key}
            code, lines = self.run_check(env)
            self.assertEqual(code, 1, key)
            self.assertIn(f"[ ] {key}", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
