"""Speaking the daily reminder: what is said, and when WhatsApp allows it to be said.
No network, nothing sent.

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_briefing -v
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock

from adviser import briefing, memory, speech

DAY = 24 * 3600
NOW = datetime(2026, 9, 23, 8, 5).timestamp()
LONG = ("Look over the changes you made to the router and the weather adapter, then commit them "
        "before you start anything else, because that work only exists on this laptop right now. ") * 3


def project(name, status="unfinished", why="no work for 9 days", left="You added the router.",
            step="Wire the weather agent into the router."):
    return {"name": name, "status": status, "why": why, "left_off": left, "next_step": step}


def briefing_file(sent_at, *projects):
    return {"sent_at": sent_at, "featured": projects[0]["name"] if projects else None,
            "whatsapp_ref": "wamid.1", "projects": list(projects)}


class FakeClient:
    def __init__(self, fail_on=None):
        self.voices, self.texts, self.fail_on = [], [], fail_on

    def send_voice(self, to, ogg):
        if not isinstance(ogg, (bytes, bytearray)):       # the real client uploads bytes, never a list
            raise TypeError(f"send_voice wants bytes, got {type(ogg).__name__}")
        if self.fail_on is not None and len(self.voices) == self.fail_on:
            raise RuntimeError("Meta said no")
        self.voices.append((to, ogg))
        return f"wamid.v{len(self.voices)}"

    def send_text(self, to, body):
        self.texts.append((to, body))
        return "wamid.t1"


class FakeServices:
    """Only what Speaker touches. render_note returns a LIST of notes, exactly like speech.render_note:
    a fake that returned bytes once hid a bug that made the whole feature fail in production."""

    def __init__(self, base_dir, env=None, client=None, clock_at=NOW):
        self.base_dir, self.env = base_dir, dict(env or {})
        self.client = client or FakeClient()
        self.now = clock_at
        self.clock = lambda: self.now
        self.store = memory.Store(base_dir, clock=self.clock)
        self.rendered, self.render_calls = [], []

    def render_note(self, text, voice="v", rate="+0%"):
        self.rendered.append(text)
        self.render_calls.append({"text": text, "voice": voice, "rate": rate})
        return [b"OggS-fake-" + text[:8].encode("utf-8", "replace")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-brief-")
        os.makedirs(os.path.join(self.tmp, ".state", "adviser"), exist_ok=True)
        self.svc = FakeServices(self.tmp)
        self.speaker = self.new_speaker()

    def new_speaker(self, **kw):
        kw.setdefault("retry_after", 0)               # tests drive the clock; no waiting between tries
        return briefing.Speaker(self.svc, "254700000512", **kw)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_briefing(self, sent_at="2026-09-23T08:00:00", *projects):
        data = briefing_file(sent_at, *(projects or (project("soc-agents"),)))
        with open(os.path.join(self.tmp, ".state", "briefing.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return data

    def owner_wrote(self, when=None):
        self.svc.store.note_inbound(self.svc.now if when is None else when)

    def state(self):
        with open(self.speaker.path, encoding="utf-8") as fh:
            return json.load(fh)

    def spoken_text(self):
        return " ".join(self.svc.rendered)


class ScriptTests(unittest.TestCase):
    def test_one_project_is_named_in_the_first_line(self):
        text = briefing.script(briefing_file("2026-09-23T08:00:00", project("soc-agents")),
                               datetime(2026, 9, 23, 8, 5))
        self.assertTrue(text.startswith("Good morning. Here is your project check-in. "
                                        "One project needs you today: soc-agents."), text)
        self.assertIn("No work for 9 days.", text)
        self.assertIn("Where you left off: You added the router.", text)
        self.assertIn("Your next step, about fifteen minutes: Wire the weather agent into the router.", text)
        self.assertIn("The full list is in that email.", text)
        self.assertNotIn("First,", text)

    def test_two_projects_are_both_described_and_nothing_is_counted(self):
        text = briefing.script(briefing_file("x", project("a"), project("b")), datetime(2026, 9, 23, 8, 0))
        self.assertIn("Two projects need you today.", text)
        self.assertIn("First, a.", text)
        self.assertIn("Then, b.", text)
        self.assertNotIn("more in today's email", text)          # exactly MAX_SPOKEN: nothing is left over

    def test_more_projects_than_are_spoken_are_counted(self):
        text = briefing.script(briefing_file("x", project("a"), project("b"), project("c"), project("d")),
                               datetime(2026, 9, 23, 13, 0))
        self.assertIn("Good afternoon.", text)
        self.assertIn("Four projects need you today.", text)
        self.assertNotIn("c.", text.split("Then, b.")[1].split("There are")[0])   # only two are described
        self.assertIn("There are two more in today's email.", text)

    def test_one_extra_project_reads_in_the_singular(self):
        text = briefing.script(briefing_file("x", project("a"), project("b"), project("c")),
                               datetime(2026, 9, 23, 20, 0))
        self.assertIn("Good evening.", text)
        self.assertIn("There is one more in today's email.", text)

    def test_there_is_an_opener_for_every_project_that_is_spoken(self):
        self.assertGreaterEqual(len(briefing.OPENERS), briefing.MAX_SPOKEN)       # or script() would crash
        many = [project(chr(ord("a") + i)) for i in range(briefing.MAX_SPOKEN)]
        text = briefing.script(briefing_file("x", *many), datetime(2026, 9, 23, 8, 0))
        for i in range(briefing.MAX_SPOKEN):
            self.assertIn(briefing.OPENERS[i], text)

    def test_greeting_changes_with_the_hour(self):
        hours = {h: briefing.greeting(datetime(2026, 9, 23, h, 30)) for h in (0, 11, 12, 17, 18, 23)}
        self.assertEqual(hours, {0: "Good morning.", 11: "Good morning.", 12: "Good afternoon.",
                                 17: "Good afternoon.", 18: "Good evening.", 23: "Good evening."})

    def test_finished_and_non_projects_are_left_out(self):
        data = briefing_file("x", project("done", status="probably_done"), project("junk", status="not_a_project"),
                             project("real", status="unclear"))
        text = briefing.script(data, datetime(2026, 9, 23, 8, 0))
        self.assertIn("One project needs you today: real.", text)
        for name in ("done", "junk"):
            self.assertNotIn(name, text)

    def test_a_project_without_a_status_is_still_spoken(self):
        text = briefing.script({"projects": [{"name": "app", "next_step": "Commit the work."}]},
                               datetime(2026, 9, 23, 8, 0))
        self.assertIn("app", text)                                # unknown status is treated as "unclear"

    def test_nothing_worth_saying_gives_an_empty_script(self):
        for data in ({}, {"projects": []}, briefing_file("x", project("done", status="probably_done")),
                     {"projects": ["junk", None, {"status": "unfinished"}]}):
            self.assertEqual(briefing.script(data, datetime(2026, 9, 23, 8, 0)), "")

    def test_nothing_is_read_out_as_markup(self):
        data = briefing_file("x", project("app", why="*work at risk*", left="`git status` shows changes",
                                          step="Run **the tests**"))
        text = briefing.script(data, datetime(2026, 9, 23, 8, 0))
        for mark in ("*", "`"):
            self.assertNotIn(mark, text)
        self.assertIn("Run the tests.", text)

    def test_a_runaway_field_is_cut_so_the_check_in_stays_short(self):
        data = briefing_file("x", project("app", left="x " * 5000, step="y " * 5000))
        text = briefing.script(data, datetime(2026, 9, 23, 8, 0))
        self.assertLess(len(text), 4 * briefing.FIELD_CHARS)
        self.assertNotIn("  ", text)

    def test_every_sentence_ends_cleanly(self):
        data = briefing_file("x", project("app", why="no work for 3 days", left="Half a thought", step="Do it"))
        text = briefing.script(data, datetime(2026, 9, 23, 8, 0))
        self.assertIn("Half a thought.", text)
        self.assertIn("Do it.", text)
        self.assertNotIn("..", text)


class WindowTests(Base):
    """WhatsApp allows a voice note only within 24 hours of the owner's own message."""

    def test_the_window_is_inside_metas_twenty_four_hours(self):
        self.assertLessEqual(briefing.WINDOW_SECONDS, 24 * 3600)   # Meta's limit; outside it the send fails 131047
        self.assertGreater(briefing.WINDOW_SECONDS, 20 * 3600)     # but still most of a day

    def test_nothing_is_spoken_before_the_owner_has_ever_written(self):
        self.write_briefing()
        self.assertEqual(self.speaker.tick(), "waiting")
        self.assertEqual(self.svc.client.voices, [])
        self.assertFalse(os.path.exists(self.speaker.path))       # not recorded: it still owes the owner

    def test_it_is_spoken_once_the_owner_has_written(self):
        self.write_briefing()
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "spoken")
        self.assertTrue(self.svc.client.voices)
        self.assertIn("One project needs you today: soc-agents.", self.spoken_text())
        self.assertEqual({to for to, _ in self.svc.client.voices}, {"254700000512"})

    def test_the_voice_and_rate_from_the_settings_are_used(self):
        self.svc.env.update(ADVISER_VOICE="en-KE-ChilembaNeural", ADVISER_VOICE_RATE="+8%")
        self.write_briefing()
        self.owner_wrote()
        self.speaker.tick()
        self.assertTrue(self.svc.render_calls)
        for call in self.svc.render_calls:
            self.assertEqual((call["voice"], call["rate"]), ("en-KE-ChilembaNeural", "+8%"))

    def test_the_default_voice_is_used_when_nothing_is_set(self):
        self.write_briefing()
        self.owner_wrote()
        self.speaker.tick()
        self.assertEqual(self.svc.render_calls[0]["voice"], speech.DEFAULT_VOICE)
        self.assertEqual(self.svc.render_calls[0]["rate"], "+0%")

    def test_a_check_in_is_spoken_only_once(self):
        self.write_briefing()
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "spoken")
        before = len(self.svc.client.voices)
        for _ in range(3):
            self.assertEqual(self.speaker.tick(), "nothing new")
        self.assertEqual(len(self.svc.client.voices), before)

    def test_the_reminders_own_retry_does_not_say_it_again(self):
        """The reminder runs every half hour until both channels are done, and each send rewrites
        the file with a new time and the same words."""
        self.write_briefing("2026-09-23T08:00:00", project("soc-agents"))
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "spoken")
        notes = len(self.svc.client.voices)
        self.svc.now += 30 * 60
        self.write_briefing("2026-09-23T08:30:00", project("soc-agents"))     # same content, later stamp
        self.assertEqual(self.speaker.tick(), "nothing new")
        self.assertEqual(len(self.svc.client.voices), notes)

    def test_tomorrows_check_in_is_spoken_again_even_if_it_reads_the_same(self):
        self.write_briefing("2026-09-23T08:00:00", project("soc-agents"))
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "spoken")
        self.svc.now += DAY
        self.owner_wrote()
        self.write_briefing("2026-09-24T08:00:00", project("soc-agents"))     # identical words, next day
        self.assertEqual(self.speaker.tick(), "spoken")

    def test_the_window_closes_after_a_day(self):
        self.write_briefing()
        self.owner_wrote(self.svc.now - briefing.WINDOW_SECONDS - 60)
        self.assertEqual(self.speaker.tick(), "waiting")
        self.assertEqual(self.svc.client.voices, [])
        self.owner_wrote()                                        # the owner writes again: it goes out
        self.assertEqual(self.speaker.tick(), "spoken")

    def test_a_message_time_in_the_future_is_ignored(self):
        """A wrong laptop clock once stored would hold the window shut for ever."""
        self.owner_wrote(self.svc.now + 3600)
        self.assertEqual(self.svc.store.last_inbound(), 0.0)
        self.owner_wrote(self.svc.now + 60)                       # a little ahead is fine (clock skew)
        self.assertEqual(self.svc.store.last_inbound(), self.svc.now + 60)

    def test_a_stored_future_time_still_reads_as_closed(self):
        memory._write_json(os.path.join(self.tmp, ".state", "adviser", "window.json"),
                           {"last_inbound": self.svc.now + 9999})
        self.assertFalse(self.speaker.window_open(self.svc.now))

    def test_the_last_message_time_only_moves_forward(self):
        self.owner_wrote(NOW)
        self.owner_wrote(NOW - 500)                               # an older message arriving late
        self.assertEqual(self.svc.store.last_inbound(), NOW)
        self.svc.now = NOW + 10
        self.owner_wrote(NOW + 10)
        self.assertEqual(self.svc.store.last_inbound(), NOW + 10)

    def test_a_damaged_window_file_reads_as_never(self):
        with open(os.path.join(self.tmp, ".state", "adviser", "window.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(self.svc.store.last_inbound(), 0.0)
        self.write_briefing()
        self.assertEqual(self.speaker.tick(), "waiting")


class DecisionTests(Base):
    def test_an_old_check_in_is_never_read_out(self):
        self.write_briefing("2026-09-22T08:00:00")                # yesterday: the adviser was off
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "stale")
        self.assertEqual(self.svc.client.voices, [])
        self.assertEqual(self.speaker.tick(), "nothing new")      # and it is not reconsidered later

    def test_a_check_in_with_nothing_to_do_is_not_spoken(self):
        self.write_briefing("2026-09-23T08:00:00", project("done", status="probably_done"))
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "nothing to say")
        self.assertEqual(self.svc.client.voices, [])

    def test_text_mode_is_respected(self):
        self.write_briefing()
        self.owner_wrote()
        conv = self.svc.store.conversation()
        conv["mode"] = "text"
        self.svc.store.save(conv)
        self.assertEqual(self.speaker.tick(), "text mode")
        self.assertEqual(self.svc.client.voices, [])

    def test_it_can_be_switched_off(self):
        self.svc.env["ADVISER_DAILY_VOICE"] = "off"
        self.write_briefing()
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "off")
        self.assertEqual(self.svc.client.voices, [])

    def test_no_reminder_yet_is_quiet(self):
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "nothing new")

    def test_what_was_said_joins_the_conversation_where_the_model_reads_it(self):
        from adviser import brain
        self.write_briefing()
        self.owner_wrote()
        self.speaker.tick()
        messages = self.svc.store.conversation()["messages"]
        self.assertEqual([m["role"] for m in messages], ["assistant"])
        self.assertIn("soc-agents", messages[0]["text"])
        self.assertEqual(messages[0]["via"], "voice")
        kept = brain.build_messages(messages, "what about it?", "voice", "snapshot",
                                    datetime.fromtimestamp(self.svc.now))
        self.assertTrue(any("soc-agents" in str(getattr(m, "content", "")) for m in kept),
                        "the model must be able to see what was just spoken")


class FailureTests(Base):
    def test_a_failed_send_is_retried_then_given_up(self):
        self.assertTrue(2 <= briefing.MAX_ATTEMPTS <= 6)          # enough to ride out a blip, not endless
        self.svc.client = FakeClient(fail_on=0)                   # every send fails
        self.write_briefing()
        self.owner_wrote()
        for attempt in range(briefing.MAX_ATTEMPTS):
            self.assertEqual(self.speaker.tick(), "failed", attempt)
            self.assertIsNone(self.state().get("spoken_for"), attempt)
        self.assertEqual(self.speaker.tick(), "failed")           # the budget is spent
        self.assertEqual(self.speaker.tick(), "nothing new")      # and recorded, so it stops trying
        self.assertEqual(self.svc.client.voices, [])

    def test_attempts_are_spaced_out_so_a_short_blip_does_not_lose_the_day(self):
        speaker = self.new_speaker(retry_after=briefing.RETRY_AFTER)
        self.svc.client = FakeClient(fail_on=0)
        self.write_briefing()
        self.owner_wrote()
        self.assertEqual(speaker.tick(), "failed")
        self.assertEqual(speaker.tick(), "waiting")               # a minute later: not another attempt
        self.svc.now += briefing.RETRY_AFTER + 1
        self.owner_wrote()
        self.svc.client.fail_on = None                            # by now the blip is over
        self.assertEqual(speaker.tick(), "spoken")

    def test_failures_on_earlier_days_do_not_count_against_today(self):
        self.svc.client = FakeClient(fail_on=0)
        self.write_briefing("2026-09-23T08:00:00")
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "failed")
        self.svc.now += DAY
        self.owner_wrote()
        self.write_briefing("2026-09-24T08:00:00", project("portfolio"))
        self.svc.client.fail_on = None
        self.assertEqual(self.speaker.tick(), "spoken")           # a fresh budget for a fresh check-in

    def test_a_partly_spoken_check_in_sends_the_rest_as_text_and_is_not_repeated(self):
        self.svc.client = FakeClient(fail_on=1)                   # the first note lands, the second fails
        self.write_briefing("2026-09-23T08:00:00", project("app", left=LONG, step=LONG))
        self.owner_wrote()
        self.assertEqual(self.speaker.tick(), "failed")
        self.assertEqual(len(self.svc.client.voices), 1)
        self.assertEqual(len(self.svc.client.texts), 1)           # the rest arrives as text
        self.assertTrue(self.svc.client.texts[0][1].strip())
        self.assertEqual(self.speaker.tick(), "nothing new")      # never said twice
        self.assertEqual(len(self.svc.client.voices), 1)

    def test_an_interrupted_send_is_not_repeated_on_the_next_start(self):
        """The claim is written before the first note, so a crash between sending and recording
        cannot turn into the same voice note again and again."""
        self.write_briefing()
        self.owner_wrote()
        # The laptop was closed (or the process killed) after the claim was written and before the
        # outcome could be: no exception handler ran, so only the claim is on disk.
        self.speaker._write({"claimed": "2026-09-23T08:00:00", "claimed_at": self.svc.now})
        self.assertEqual(self.speaker.tick(), "nothing new")
        self.assertEqual(self.svc.client.voices, [])
        self.assertIn("interrupted", self.state()["how"])

    def test_nothing_is_sent_when_the_record_cannot_be_written(self):
        self.write_briefing()
        self.owner_wrote()
        with mock.patch.object(briefing.Speaker, "_write", return_value=False):
            self.assertEqual(self.speaker.tick(), "failed")
        self.assertEqual(self.svc.client.voices, [])

    def test_a_crash_inside_the_tick_is_caught(self):
        self.write_briefing()
        self.owner_wrote()
        self.svc.render_note = lambda *a, **kw: (_ for _ in ()).throw(BaseException("boom"))
        self.assertEqual(self.speaker.tick(), "failed")

    def test_two_threads_cannot_speak_the_same_check_in(self):
        self.write_briefing()
        self.owner_wrote()
        results, threads = [], [threading.Thread(target=lambda: results.append(self.speaker.tick()))
                                for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count("spoken"), 1, results)
        self.assertEqual(sorted(set(results) - {"spoken"}), ["busy", "nothing new"][:len(set(results)) - 1])
        notes = [ogg for _, ogg in self.svc.client.voices]
        self.assertEqual(len(notes), len(set(notes)), "the same note was sent twice")
        self.assertEqual(len(notes), len(self.svc.render_calls))   # one run's worth of notes, no more

    def test_another_process_cannot_speak_at_the_same_time(self):
        """`adviser brief` in one window while the service runs in another: the lock is a file,
        because a thread lock means nothing across processes."""
        self.write_briefing()
        self.owner_wrote()
        other = self.new_speaker()                                 # stands in for the second process
        fd = other._take_lock()
        try:
            self.assertEqual(self.speaker.tick(), "busy")
            self.assertEqual(self.svc.client.voices, [])
        finally:
            other._drop_lock(fd)
        self.assertEqual(self.speaker.tick(), "spoken")            # once the other one is done

    def test_a_lock_left_behind_by_a_dead_process_is_reclaimed(self):
        self.write_briefing()
        self.owner_wrote()
        with open(self.speaker.lock_path, "w", encoding="utf-8") as fh:
            fh.write("4242")
        old = time.time() - briefing.LOCK_STALE_SECONDS - 60
        os.utime(self.speaker.lock_path, (old, old))
        self.assertEqual(self.speaker.tick(), "spoken")
        self.assertFalse(os.path.exists(self.speaker.lock_path))


class BackgroundTests(Base):
    def test_the_timer_thread_speaks_and_then_stops_when_asked(self):
        self.write_briefing()
        self.owner_wrote()
        stop = threading.Event()
        thread = threading.Thread(target=self.speaker.run_forever, args=(stop, 0.01), daemon=True)
        thread.start()
        for _ in range(200):                                       # up to 2 s
            if self.svc.client.voices:
                break
            time.sleep(0.01)
        stop.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(self.svc.client.voices, "the background loop never spoke the check-in")
        self.assertEqual(self.state()["spoken_for"], "2026-09-23T08:00:00")

    def test_the_timer_checks_often_enough_to_follow_the_reminder(self):
        self.assertLessEqual(briefing.TICK_SECONDS, 300)


if __name__ == "__main__":
    unittest.main()
