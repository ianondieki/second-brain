"""One conversation turn end to end with fakes: hear, route, think, speak, deliver, memory.

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_turn -v
"""
import json
import os
import time

from adviser import brain, memory, speech, turn
from adviser.whatsapp import Inbound
from tests.adviser_fakes import LIVE_WRAPPED_REPLY, OWNER, FakeClient, TempBrain, scripted, tool_call


def text(mid, body, reply_to=""):
    return Inbound(id=mid, sender=OWNER, timestamp=int(time.time()), kind="text", text=body, reply_to=reply_to)


def voice(mid):
    return Inbound(id=mid, sender=OWNER, timestamp=int(time.time()), kind="voice", media_id="m-" + mid, mime="audio/ogg")


class Clock:
    def __init__(self, t=None):
        self.t = t or time.time()

    def __call__(self):
        return self.t


class TurnTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.client = FakeClient()
        self.heard = []
        self.spoken = []
        self.transcript = speech.Transcript("where did I leave off on sock agents", "en", 3.0)

    def services(self, *replies, pool=True, env=None, voice_fails=False, stt_fails=False, clock=None):
        self.llm = scripted(*replies)
        clock = clock or Clock()

        def transcribe(audio, mime, key, hint=""):
            self.heard.append((audio, mime, key, hint))
            if stt_fails:
                raise speech.SpeechError("bad audio")
            return self.transcript

        def render_note(part, voice, rate):
            self.spoken.append((part, voice, rate))
            if voice_fails is True or (voice_fails and len(self.spoken) in voice_fails):
                raise speech.SpeechError("tts down")
            return [f"OggS-{part[:12]}".encode()]
        p = brain.ModelPool([("fake", self.llm)], clock=clock, sleep=lambda s: None) if pool else None
        return turn.Services(base_dir=self.base, env=env or {"GROQ_API_KEY": "k"}, client=self.client,
                             store=memory.Store(self.base, clock=clock), portfolio=brain.Portfolio(self.base, clock=clock),
                             pool=p, transcribe=transcribe, render_note=render_note, clock=clock)

    def run_turn(self, svc, *msgs):
        return turn.handle(turn.build_turn(svc), list(msgs), OWNER)

    def conv(self):
        return self.read_json(".state/adviser/conversation.json")

    # ------------------------------------------------------------------ happy paths

    def test_text_in_text_out_with_memory(self):
        svc = self.services("You left soc-agents at the runbook page.")
        result = self.run_turn(svc, text("w1", "What next on soc-agents?"))
        self.assertEqual(self.client.kinds(), ["read", "text"])
        self.assertEqual(self.client.calls[0], ("read", "w1", True))
        self.assertEqual(self.client.texts(), ["You left soc-agents at the runbook page."])
        self.assertEqual(result["mode"], "text")
        roles = [(m["role"], m["text"]) for m in self.conv()["messages"]]
        self.assertEqual(roles, [("user", "What next on soc-agents?"),
                                 ("assistant", "You left soc-agents at the runbook page.")])
        self.assertIn("WhatsApp text message", self.llm.seen[0][0].content)

    def test_voice_in_voice_out(self):
        svc = self.services("Sure. You stopped at the runbook page. Want to start it now?")
        result = self.run_turn(svc, voice("w2"))
        self.assertEqual(self.client.kinds(), ["read", "download", "voice"])
        self.assertEqual(self.client.calls[2][2], b"OggS-Sure. You st")
        self.assertIn("portfolio, soc-agents", self.heard[0][3])          # project names help Whisper
        self.assertEqual(self.spoken[0][1], speech.DEFAULT_VOICE)
        self.assertEqual(result["mode"], "voice")
        self.assertIn("SPOKEN", self.llm.seen[0][0].content)
        self.assertEqual(self.llm.seen[0][-1].content,
                         f"where did I leave off on sock agents\n\n{brain.VOICE_NUDGE}")
        self.assertEqual(self.conv()["messages"][0]["text"], "where did I leave off on sock agents")
        self.assertEqual(self.conv()["messages"][0]["via"], "voice")

    def test_readable_part_goes_as_a_separate_text(self):
        svc = self.services("Commit first, then push.\n[[text]]\ngit add -A\ngit commit -m wip")
        self.run_turn(svc, voice("w3"))
        self.assertEqual(self.client.kinds(), ["read", "download", "voice", "text"])
        self.assertEqual(self.spoken[0][0], "Commit first, then push.")
        self.assertEqual(self.client.texts(), ["```\ngit add -A\ngit commit -m wip\n```"])   # monospace on WhatsApp

    def test_long_answer_streams_short_first_note_then_the_rest_in_order(self):
        long = " ".join(f"Point {i} is about the scheduler and the runbook." for i in range(30))
        svc = self.services(long)
        self.run_turn(svc, voice("w11"))
        voices = [c[2] for c in self.client.calls if c[0] == "voice"]
        parts = [p for p, _, _ in self.spoken]
        self.assertGreater(len(voices), 2)
        self.assertLessEqual(len(parts[0]), speech.FIRST_CHARS)
        self.assertEqual(voices, [f"OggS-{p[:12]}".encode() for p in parts])
        self.assertEqual(" ".join(parts), long)
        rest = [len(p) for p in parts[1:]]
        self.assertLess(max(rest) - min(rest), 260)                       # evenly sized after the opener

    def test_later_note_failing_sends_the_rest_as_text(self):
        long = " ".join(f"Point {i} is about the scheduler and the runbook." for i in range(30))
        svc = self.services(long, voice_fails={2})
        self.run_turn(svc, voice("w12"))
        self.assertEqual(self.client.kinds(), ["read", "download", "voice", "text"])
        spoken_first = self.client.calls[2][2]
        rest = self.client.texts()[0]
        self.assertTrue(long.startswith(self.spoken[0][0]))
        self.assertTrue(long.endswith(rest))
        self.assertEqual(len(self.spoken[0][0]) + 1 + len(rest), len(long))

    def test_code_is_never_spoken_it_goes_as_monospace_text(self):
        svc = self.services(LIVE_WRAPPED_REPLY)
        self.run_turn(svc, voice("w13"))
        spoken = " ".join(p for p, _, _ in self.spoken)
        self.assertNotIn("import", spoken)
        self.assertNotIn("pip", spoken)
        self.assertTrue(spoken.startswith("Set up a tiny scheduler first."))
        self.assertEqual(self.client.kinds()[-1], "text")
        sent = self.client.texts()[-1]
        self.assertEqual([p for p, _, _ in self.spoken],
                         ["Set up a tiny scheduler first. Want me to walk you through the exact code skeleton "
                          "for that 15-minute setup?"])
        self.assertTrue(sent.startswith("*schedule_brief.py*\n\n```\npip install APScheduler==3.10.4"))
        self.assertIn("def send_brief():\n    brief = run_proactive_brief()", sent)
        self.assertTrue(sent.endswith("scheduler.start()\n```"))

    def test_asking_for_voice_in_text_gets_voice(self):
        svc = self.services("Here you go.")
        self.run_turn(svc, text("w4", "send me a voice note about portfolio"))
        self.assertIn("voice", self.client.kinds())

    def test_swahili_voice_note_gets_swahili_voice(self):
        self.transcript = speech.Transcript("nieleze kuhusu portfolio", "sw", 2.0)
        svc = self.services("Sawa.")
        self.run_turn(svc, voice("w5"))
        self.assertEqual(self.spoken[0][1], speech.SWAHILI_VOICE)

    def test_messages_that_arrive_together_are_one_turn(self):
        svc = self.services("Both answered.")
        self.run_turn(svc, text("a", "hi"), text("b", "tell me about portfolio"))
        self.assertEqual(self.llm.seen[0][-1].content, "hi\ntell me about portfolio")
        self.assertEqual(self.client.calls[0], ("read", "b", True))
        self.assertEqual(self.client.kinds().count("text"), 1)

    def test_looks_at_files_before_answering(self):
        svc = self.services(tool_call("read_project_file", project="soc agents", path="README.md"),
                            "Your next open item is the runbook page.")
        result = self.run_turn(svc, text("w6", "expound on soc-agents"))
        self.assertEqual(result["trace"], ["read_project_file(project='soc agents', path='README.md')"])
        self.assertEqual(self.client.texts(), ["Your next open item is the runbook page."])

    # ------------------------------------------------------------------ never silent

    def test_unheard_voice_note_asks_again(self):
        svc = self.services("unused", stt_fails=True)
        self.run_turn(svc, voice("w7"))
        self.assertEqual(self.client.texts(), [turn.DEAF])
        self.assertEqual(self.llm.seen, [])

    def test_photos_and_reactions(self):
        svc = self.services("unused")
        self.run_turn(svc, Inbound(id="p", sender=OWNER, timestamp=1, kind="other", raw_type="image"))
        self.assertEqual(self.client.texts(), [turn.UNSUPPORTED])
        self.client.calls.clear()
        self.run_turn(svc, Inbound(id="r", sender=OWNER, timestamp=1, kind="reaction", text="\U0001F44D"))
        self.assertEqual(self.client.kinds(), ["read"])                   # a thumbs-up needs no answer

    def test_no_model_means_an_apology_not_silence(self):
        svc = self.services(pool=False)
        self.run_turn(svc, voice("w8"))
        self.assertEqual(self.client.texts(), [turn.BUSY])

    def test_speech_failure_falls_back_to_text(self):
        svc = self.services("Plain answer.", voice_fails=True)
        self.run_turn(svc, voice("w9"))
        self.assertEqual(self.client.texts(), ["Plain answer."])

    def test_voice_upload_failure_falls_back_to_text(self):
        self.client = FakeClient(fail_voice=True)
        svc = self.services("Plain answer.")
        self.run_turn(svc, voice("w10"))
        self.assertEqual(self.client.texts(), ["Plain answer."])

    # ------------------------------------------------------------------ commands

    def test_commands(self):
        svc = self.services("A voice answer.")
        self.run_turn(svc, text("c1", "/voice"))
        self.assertEqual(self.conv()["mode"], "voice")
        self.run_turn(svc, text("c2", "how is portfolio?"))
        self.assertIn("voice", self.client.kinds())
        self.run_turn(svc, text("c3", "/auto"))
        self.assertEqual(self.conv()["mode"], "mirror")
        self.run_turn(svc, text("c4", "/projects"))
        self.assertIn("*portfolio*: needs attention", self.client.texts()[-1])
        self.run_turn(svc, text("c5", "/reset"))
        self.assertEqual(self.conv()["messages"], [])
        self.run_turn(svc, text("c6", "/nonsense"))
        self.assertIn("I do not know /nonsense", self.client.texts()[-1])
        self.assertEqual(len(self.llm.seen), 1)                            # only c2 reached the model

    # ------------------------------------------------------------------ confirmed reminder changes

    def test_proposal_then_yes_changes_reminders(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Nice work! Shall I stop reminding you about portfolio?")
        self.run_turn(svc, text("y1", "I finished portfolio"))
        self.assertEqual(self.conv()["pending"]["project"], "portfolio")
        self.assertEqual(self.read_json("reminders.json")["done"], [])        # nothing changed yet
        self.run_turn(svc, text("y2", "Yes please"))
        settings = self.read_json("reminders.json")
        self.assertEqual(settings["done"], ["portfolio"])
        self.assertEqual(settings["_help"], "test settings")                  # comments survive
        self.assertIn("marked portfolio as finished", self.client.texts()[-1])
        self.assertIsNone(self.conv()["pending"])
        self.assertTrue(os.path.exists(os.path.join(self.base, ".state", "reminders.json.bak")))
        self.assertEqual(len(self.llm.seen), 2)                               # "yes" never reached the model

    def test_a_false_claim_of_change_is_replaced_by_the_question(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Great job. I've marked the portfolio project as finished in the reminder system. "
                            "Shall I stop reminding you about it?")
        self.run_turn(svc, text("f1", "Honestly I think portfolio is finished."))
        self.assertEqual(self.client.texts()[-1],
                         "Great job. Shall I stop reminding you about portfolio? Say yes or no.")
        self.assertEqual(self.read_json("reminders.json")["done"], [])

    def test_a_yes_to_the_models_own_wording_is_never_enough(self):
        # The model asked in its own words and forgot the tool. The owner's "yes" makes it propose;
        # the change still waits for a yes to the fixed question (the review's H2).
        svc = self.services("Got it. *Shall I set the reminder for *portfolio* to “done” now?*",
                            tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Done deal.")
        self.run_turn(svc, text("q1", "Honestly I think portfolio is finished."))
        self.assertIsNone(self.conv().get("pending"))
        self.run_turn(svc, text("q2", "yes"))
        self.assertEqual(self.read_json("reminders.json")["done"], [])
        self.assertTrue(self.client.texts()[-1].endswith("Shall I stop reminding you about portfolio? Say yes or no."))
        self.run_turn(svc, text("q3", "yes"))
        self.assertEqual(self.read_json("reminders.json")["done"], ["portfolio"])

    def test_only_a_clear_yes_applies(self):
        yes = ("yes", "Yes please.", "ok, go ahead", "Sure, thanks", "ndio", "Ndiyo", "Absolutely", "Of course",
               "Definitely", "Go for it", "yea", "\U0001F44D", "\U0001F44D️", "sure thing", "ok thanks")
        no = ("no", "No thanks", "no, leave it for now", "nope", "hapana", "not yet", "Hold on", "later",
              "\U0001F44E", "No, don’t", "dont")
        # Round 1 and round 2 of the review: every one of these once applied a change.
        unclear = ("Okay, no thanks", "ok wait, don't", "Yes but no", "Sure? why would I want that",
                   "ya know what, leave it", "OK so what's left in portfolio?", "Correct me if I'm wrong",
                   "Yes, don’t do that", "Yes, not yet", "Yes, hold on", "Yes, nevermind", "Yes, scratch that",
                   "Ndio, lakini subiri", "Sawa, usifanye", "Yes, keep it", "Yes, leave it", "Yes, rather snooze it",
                   "Yes, I mean the other project", "Yes, never", "Yes, later", "Ndio, si sasa", "Yes, \U0001F6D1",
                   "Okay...", "yes, and then tell me what to do on soc-agents today", "Yes!!! but wait")
        for said in yes:
            self.assertEqual(turn.yes_or_no(said), "yes", said)
        for said in no:
            self.assertEqual(turn.yes_or_no(said), "no", said)
        for said in unclear:
            self.assertEqual(turn.yes_or_no(said), "unclear", said)
        self.assertEqual(turn.yes_or_no("what about soc-agents, what should I do there today, and the tests?"), "other")

    def test_unclear_answer_asks_again_and_changes_nothing(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"), "Nice.")
        self.run_turn(svc, text("c1", "portfolio is done"))
        self.run_turn(svc, text("c2", "Okay, no thanks"))
        self.assertEqual(self.read_json("reminders.json")["done"], [])
        self.assertEqual(self.client.texts()[-1], "Sorry, I need a clear yes or no. "
                                                  "Shall I stop reminding you about portfolio? Say yes or no.")
        self.assertEqual(self.conv()["pending"]["project"], "portfolio")
        self.run_turn(svc, text("c3", "no"))
        self.assertEqual(self.read_json("reminders.json")["done"], [])
        self.assertIsNone(self.conv()["pending"])
        self.assertEqual(len(self.llm.seen), 2)                               # "ok no thanks" and "no" never reached it

    def test_a_question_that_never_arrived_cannot_be_answered(self):
        class TextFails(FakeClient):
            def send_text(self, to, body):
                raise RuntimeError("network down")
        self.client = TextFails()
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"), "Nice.")
        self.run_turn(svc, text("n1", "portfolio is done"))
        self.assertIsNone(self.conv().get("pending"))                        # the review's L5

    def test_real_errors_are_not_called_overload(self):
        svc = self.services("unused")
        svc.portfolio.refresh = lambda *a, **k: (_ for _ in ()).throw(ValueError("projects root not found"))
        self.run_turn(svc, text("e1", "hi"))
        self.assertIn("something went wrong on my side (ValueError)", self.client.texts()[-1])

    def test_a_crashing_turn_still_apologises(self):
        sent = []

        class Boom:
            def invoke(self, state):
                raise RuntimeError("graph broke")
        result = turn.handle(Boom(), [text("x", "hi")], OWNER, apologise=lambda to, body: sent.append((to, body)))
        self.assertIn("error", result)
        self.assertEqual(sent[0][0], OWNER)
        self.assertIn("(RuntimeError)", sent[0][1])

    def test_failed_note_does_not_wait_for_the_others(self):
        import threading
        release = threading.Event()
        svc = self.services(" ".join(f"Point {i} is about the scheduler and the runbook." for i in range(30)))

        def render(part, voice, rate):
            if part.startswith("Point 0"):
                return [b"OggS-first"]
            if svc.render_calls == 0:
                svc.render_calls = 1
                raise speech.SpeechError("tts down")
            release.wait(20)                                  # a slow note still being made
            return [b"OggS-late"]
        svc.render_calls = 0
        svc.render_note = render
        t0 = time.time()
        self.run_turn(svc, voice("s1"))
        elapsed = time.time() - t0
        release.set()
        self.assertLess(elapsed, 10)                          # the text fallback did not wait 20 s
        self.assertEqual(self.client.kinds()[-2:], ["voice", "text"])

    def test_yes_to_an_unrelated_question_changes_nothing(self):
        svc = self.services("Portfolio looks solid. Want me to explain the risks in portfolio?",
                            tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Here are the risks.")
        self.run_turn(svc, text("r1", "tell me about portfolio"))
        self.run_turn(svc, text("r2", "yes"))
        self.assertEqual(self.read_json("reminders.json")["done"], [])
        self.assertTrue(self.client.texts()[-1].endswith("Shall I stop reminding you about portfolio? Say yes or no."))
        self.assertEqual(self.conv()["pending"]["project"], "portfolio")

    def test_confirm_wording(self):
        p = {"project": "soc-agents", "action": "snooze", "days": 5}
        self.assertEqual(turn.confirm_proposal("Fair enough, take a break. It is now paused.", p),
                         "Fair enough, take a break. Shall I pause reminders about soc-agents for 5 days? Say yes or no.")
        self.assertEqual(turn.confirm_proposal("", {"project": "x", "action": "reopen", "days": 3}),
                         "Shall I put x back on your reminder list? Say yes or no.")
        keep = "You're now all set to deploy. I can confirm the tests pass."        # the review's L6
        self.assertEqual(turn.confirm_proposal(keep, {"project": "x", "action": "done", "days": 3}),
                         keep + " Shall I stop reminding you about x? Say yes or no.")

    def test_proposal_then_no_changes_nothing(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="snooze", days=5),
                            "Shall I pause portfolio for five days?")
        self.run_turn(svc, text("n1", "give me a break from portfolio"))
        self.run_turn(svc, text("n2", "no, leave it"))
        self.assertEqual(self.read_json("reminders.json")["snooze"], {})
        self.assertEqual(self.client.texts()[-1], "Okay, I left your reminders as they are.")

    def test_yes_with_more_gets_the_question_again(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="snooze", days=3),
                            "Shall I pause it?")
        self.run_turn(svc, text("l1", "pause portfolio"))
        self.run_turn(svc, text("l2", "yes, and then tell me what to do on soc-agents today"))
        self.assertEqual(self.read_json("reminders.json")["snooze"], {})
        self.assertTrue(self.client.texts()[-1].startswith("Sorry, I need a clear yes or no."))
        self.run_turn(svc, text("l3", "yes"))
        self.assertIn("portfolio", self.read_json("reminders.json")["snooze"])
        self.assertTrue(self.client.texts()[-1].startswith("I've paused reminders about portfolio until"))

    def test_a_claimed_change_without_a_proposal_is_removed(self):
        svc = self.services("All set. Portfolio has been marked as done and is off your list. Good luck with the next one!")
        self.run_turn(svc, text("k1", "yes"))
        self.assertEqual(self.client.texts()[-1], f"All set. Good luck with the next one! {turn.NOTHING_CHANGED}")
        self.assertEqual(self.read_json("reminders.json")["done"], [])

    def test_claims_next_to_the_question_are_removed(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Done, I marked it as finished. Portfolio has been marked as done and is off your list.")
        self.run_turn(svc, text("k2", "portfolio is finished"))
        self.assertEqual(self.client.texts()[-1], "Shall I stop reminding you about portfolio? Say yes or no.")

    def test_code_survives_when_everything_follows_the_marker(self):
        svc = self.services("[[text]]\nRun this first:\n```\npip install apscheduler\n```")
        self.run_turn(svc, voice("m1"))
        self.assertEqual([p for p, _, _ in self.spoken], ["Run this first:"])
        self.assertEqual(self.client.texts()[-1], "```\npip install apscheduler\n```")

    def test_question_lost_in_a_half_failed_reply_cannot_be_answered(self):
        class TextFails(FakeClient):
            def send_text(self, to, body):
                raise RuntimeError("network down")
        self.client = TextFails()
        long = " ".join(f"Point {i} is about the scheduler and the runbook." for i in range(30))
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"), long,
                            voice_fails={2})
        self.run_turn(svc, voice("h1"))
        self.assertEqual(self.client.kinds().count("voice"), 1)            # the question was in the lost part
        self.assertIsNone(self.conv().get("pending"))

    def test_unrelated_reply_drops_the_proposal(self):
        svc = self.services(tool_call("propose_reminder_change", project="portfolio", action="done"),
                            "Shall I?", "Something else.")
        self.run_turn(svc, text("u1", "portfolio is done"))
        self.run_turn(svc, text("u2", "what about soc-agents?"))              # short: the question stays open
        self.assertTrue(self.client.texts()[-1].startswith("Sorry, I need a clear yes or no."))
        self.run_turn(svc, text("u3", "actually tell me where I left off on soc-agents and what comes next"))
        self.assertIsNone(self.conv()["pending"])                             # longer and about something else
        self.assertEqual(self.read_json("reminders.json")["done"], [])
        self.assertEqual(self.client.texts()[-1], "Something else.")

    # ------------------------------------------------------------------ grounding on the reminder

    def test_reply_to_the_reminder_is_grounded_on_it(self):
        self.write(".state/briefing.json", json.dumps({
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60)),
            "featured": "portfolio", "whatsapp_ref": "wamid.reminder",
            "projects": [{"name": "portfolio", "status": "unfinished", "left_off": "Hero section.",
                          "next_step": "Add the contact form."}]}))
        svc = self.services("About portfolio: add the contact form next.")
        self.run_turn(svc, text("g1", "tell me more", reply_to="wamid.reminder"))
        system = self.llm.seen[0][0].content
        self.assertIn("replying to today's WhatsApp reminder, which was about portfolio", system)
        self.assertIn("left off: Hero section.; suggested next step: Add the contact form.", system)


class StoreTests(TempBrain):
    def test_dedupe_is_once_per_id(self):
        store = memory.Store(self.base)
        self.assertTrue(store.first_time("a"))
        self.assertFalse(store.first_time("a"))
        self.assertTrue(memory.Store(self.base).first_time("b"))
        self.assertFalse(memory.Store(self.base).first_time("b"))       # survives a restart

    def test_old_ids_are_forgotten(self):
        clock = Clock(1_000_000.0)
        store = memory.Store(self.base, clock=clock)
        store.first_time("old")
        clock.t += memory.SEEN_KEEP_SECONDS + 1
        self.assertTrue(store.first_time("old"))

    def test_conversation_resets_after_quiet_hours_or_a_new_reminder(self):
        clock = Clock(2_000_000_000.0)
        store = memory.Store(self.base, clock=clock)
        conv = store.conversation()
        store.add(conv, "user", "hi")
        store.save(conv)
        clock.t += 3600
        self.assertEqual(len(store.conversation()["messages"]), 1)
        clock.t += memory.IDLE_RESET_SECONDS
        self.assertEqual(store.conversation()["messages"], [])

        conv = store.conversation()
        store.add(conv, "user", "again")
        store.save(conv)
        from datetime import datetime
        later = datetime.fromtimestamp(clock.t + 60).isoformat(timespec="seconds")
        self.write(".state/briefing.json", json.dumps({"sent_at": later}))
        clock.t += 120
        self.assertEqual(store.conversation()["messages"], [])

    def test_history_is_bounded(self):
        store = memory.Store(self.base)
        conv = store.conversation()
        for i in range(30):
            store.add(conv, "user", "x" * 5000)
        store.save(conv)
        msgs = store.conversation()["messages"]
        self.assertEqual(len(msgs), memory.KEEP_MESSAGES)
        self.assertEqual(len(msgs[0]["text"]), memory.MESSAGE_CHARS)

    def test_bad_reminder_change_is_rolled_back(self):
        path = os.path.join(self.base, "reminders.json")
        with open(path, encoding="utf-8") as fh:
            before = fh.read()
        os.rename(self.root, self.root + "-moved")                   # now the config itself is invalid
        with self.assertRaises(Exception):
            memory.apply_reminder_change(self.base, "portfolio", "done")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        os.rename(self.root + "-moved", self.root)
