"""The adviser agent: portfolio, cross-project tools, model pool, agent loop (fake models).

    .venv\\Scripts\\python.exe -m unittest tests.test_adviser_brain -v
"""
import unittest
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from adviser import brain
from tests.adviser_fakes import LIVE_WRAPPED_REPLY, RateLimited, TempBrain, failing, scripted, tool_call


class PortfolioTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.pf = brain.Portfolio(self.base).refresh()

    def test_finds_projects_by_loose_names(self):
        for said in ("soc-agents", "SOC agents", "soc_agents", "socagents", "sock agents", "soc"):
            self.assertEqual(self.pf.find(said).name, "soc-agents", said)
        self.assertEqual(self.pf.find("port folio").name, "portfolio")
        self.assertIsNone(self.pf.find("kilimo orbit"))
        self.assertIsNone(self.pf.find(""))

    def test_snapshot_has_state_todos_and_reminder_verdicts(self):
        snap = self.pf.snapshot({"projects": [{"name": "portfolio", "status": "probably_done",
                                               "left_off": "Site shipped.", "next_step": "Archive it."}]})
        self.assertIn("- soc-agents: active; worked on today", snap)
        self.assertIn("1 open to-dos, first: write the runbook page", snap)
        self.assertIn("- portfolio: needs attention; last work 10 days ago", snap)
        self.assertIn("today's reminder judged it probably_done; left off: Site shipped.", snap)
        self.assertIn("not in git", snap)

    def test_cache_and_forced_refresh(self):
        calls = []

        def discover(*a, **kw):
            calls.append(1)
            return [], []
        pf = brain.Portfolio(self.base, discover_fn=discover)
        pf.refresh()
        pf.refresh()
        self.assertEqual(len(calls), 1 if pf.projects else 2)   # an empty scan is not worth caching
        pf.refresh(force=True)
        self.assertGreaterEqual(len(calls), 2)


class ToolTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.proposal = {}
        self.tools = {t.name: t for t in brain.make_adviser_tools(brain.Portfolio(self.base).refresh(), self.proposal)}

    def test_reads_any_project_with_redaction(self):
        out = self.tools["read_project_file"].invoke({"project": "sock agents", "path": "app.py"})
        self.assertIn("API_KEY = [redacted]", out)
        self.assertIn("def main", out)
        listing = self.tools["list_project_files"].invoke({"project": "portfolio"})
        self.assertIn("README.md", listing)
        self.assertNotIn(".env", listing)

    def test_refuses_unknown_projects_secrets_and_escapes(self):
        out = self.tools["read_project_file"].invoke({"project": "nope", "path": "README.md"})
        self.assertTrue(out.startswith("Refused: There is no project called 'nope'"))
        self.assertIn("portfolio, soc-agents", out)
        self.assertTrue(self.tools["read_project_file"].invoke({"project": "portfolio", "path": ".env"})
                        .startswith("Refused"))
        self.assertTrue(self.tools["read_project_file"].invoke({"project": "portfolio", "path": "../soc-agents/app.py"})
                        .startswith("Refused"))

    def test_search_and_git(self):
        self.assertIn("README.md:3:", self.tools["search_project"].invoke({"project": "soc-agents", "pattern": "runbook"}))
        self.assertEqual(self.tools["project_git"].invoke({"project": "portfolio"}), "This folder is not a git repository.")

    def test_repeated_look_up_is_not_run_twice(self):
        args = {"project": "soc-agents", "pattern": "runbook"}
        first = self.tools["search_project"].invoke(args)
        self.assertIn("README.md:3:", first)
        self.assertTrue(self.tools["search_project"].invoke(args).startswith("You already ran this exact look-up"))
        self.assertIn("README.md:3:", self.tools["search_project"].invoke({**args, "pattern": "Runbook"}))

    def test_proposal_is_only_recorded(self):
        out = self.tools["propose_reminder_change"].invoke({"project": "Portfolio", "action": "snooze", "days": 99})
        self.assertIn("nothing has changed yet", out.lower())
        self.assertEqual(self.proposal, {"project": "portfolio", "action": "snooze", "days": 60})
        self.assertEqual(self.read_json("reminders.json")["snooze"], {})
        bad = self.tools["propose_reminder_change"].invoke({"project": "ghost", "action": "done"})
        self.assertTrue(bad.startswith("Refused"))


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class PoolTests(unittest.TestCase):
    msgs = [SystemMessage("s"), HumanMessage("hi")]

    def test_falls_back_on_rate_limit_and_cools_the_model(self):
        clock = Clock()
        bad, good = failing(), scripted("from the second model", "again")
        pool = brain.ModelPool([("big", bad), ("small", good)], clock=clock, sleep=clock.sleep)
        reply = pool.invoke(self.msgs)
        self.assertEqual(reply.content, "from the second model")
        self.assertEqual(reply.response_metadata["adviser_model"], "small")
        self.assertEqual(pool.entries[0]["cool"], 1007.0)          # retry-after: 7
        pool.invoke(self.msgs)
        self.assertEqual(bad.calls, 1)                              # still cooling: not tried again

    def test_gives_up_when_everything_fails(self):
        clock = Clock()
        pool = brain.ModelPool([("a", failing()), ("b", failing(RuntimeError("500")))], clock=clock,
                               sleep=clock.sleep, max_wait=25)
        with self.assertRaises(brain.AdviserBusy):
            pool.invoke(self.msgs)
        self.assertLessEqual(sum(clock.slept), 30)

    def test_waits_for_budget_instead_of_tripping_429(self):
        clock = Clock()
        llm = scripted("one", "two")
        pool = brain.ModelPool([("only", llm)], budget=1000, clock=clock, sleep=clock.sleep, max_wait=90)
        pool.entries[0]["pacer"].after(1000)                         # the minute's budget is spent
        self.assertEqual(pool.invoke(self.msgs).content, "one")
        self.assertGreater(sum(clock.slept), 50)

    def test_waits_for_the_model_that_frees_up_first(self):
        # The review's M1: A and B are full for ~50 s, C frees up in ~4.5 s. The pool must wait for C.
        clock = Clock()
        a, b, c = scripted("a"), scripted("b"), scripted("from C")
        pool = brain.ModelPool([("A", a), ("B", b), ("C", c)], budget=7000, clock=clock, sleep=clock.sleep, max_wait=25)
        pool.entries[2]["pacer"].after(6800)                  # 6,800 + this ~400-token call > 7,000
        clock.t += 56
        pool.entries[0]["pacer"].after(6800)
        pool.entries[1]["pacer"].after(6800)
        clock.t += 10
        self.assertEqual(pool.invoke(self.msgs).content, "from C")
        self.assertLess(sum(clock.slept), 10)

    def test_errors_with_no_retry_after_do_not_spin_past_the_deadline(self):
        # Round 2, #4: "retry-after: 0" used to loop thousands of times past the deadline.
        class Zero(RateLimited):
            class response:                                   # noqa: N801
                status_code = 429
                headers = {"retry-after": "0"}
        clock = Clock()
        bad = failing(Zero("rate limited"))
        pool = brain.ModelPool([("a", bad)], clock=clock, sleep=clock.sleep, max_wait=25)
        with self.assertRaises(brain.AdviserBusy):
            pool.invoke(self.msgs)
        self.assertLess(bad.calls, 40)
        self.assertLessEqual(clock.t - 1000.0, 30)

    def test_budget_wait_longer_than_max_wait_is_busy(self):
        clock = Clock()
        pool = brain.ModelPool([("only", scripted("x"))], budget=1000, clock=clock, sleep=clock.sleep, max_wait=5)
        pool.entries[0]["pacer"].after(1000)
        with self.assertRaises(brain.AdviserBusy):
            pool.invoke(self.msgs)


class AgentTests(TempBrain):
    def setUp(self):
        super().setUp()
        self.proposal = {}
        self.pf = brain.Portfolio(self.base).refresh()
        self.tools = brain.make_adviser_tools(self.pf, self.proposal)

    def run_agent(self, llm, max_tool_calls=brain.MAX_TOOL_CALLS):
        clock = Clock()
        agent = brain.build_adviser(brain.ModelPool([("m", llm)], clock=clock, sleep=clock.sleep), self.tools,
                                    max_tool_calls)
        msgs = brain.build_messages([], "Explain soc-agents", "voice", self.pf.snapshot(), datetime(2026, 9, 22, 9, 0))
        return agent.invoke({"messages": msgs})

    def test_looks_then_answers(self):
        llm = scripted(tool_call("read_project_file", project="soc-agents", path="README.md"),
                       "It is your NOC agents project. Next, write the runbook page.")
        result = self.run_agent(llm)
        self.assertEqual(brain.reply_text(result["messages"][-1]),
                         "It is your NOC agents project. Next, write the runbook page.")
        self.assertEqual(brain.tool_trace(result["messages"]), ["read_project_file(project='soc-agents', path='README.md')"])
        tool_result = llm.seen[1][-1].content
        self.assertIn("write the runbook page", tool_result)

    def test_tool_budget_forces_an_answer(self):
        llm = scripted(tool_call("project_git", "c1", project="soc-agents"),
                       tool_call("project_git", "c2", project="portfolio"), "Answer with what I have.")
        result = self.run_agent(llm, max_tool_calls=1)
        self.assertEqual(brain.reply_text(result["messages"][-1]), "Answer with what I have.")
        self.assertIn("used all your look-ups", llm.seen[-1][-1].content)

    def test_prompt_carries_mode_time_snapshot_and_history(self):
        msgs = brain.build_messages([{"role": "user", "text": "hi", "via": "voice"},
                                     {"role": "assistant", "text": "hello"}],
                                    "and now?", "text", "SNAP", datetime(2026, 9, 22, 9, 5), "FOCUS")
        system = msgs[0].content
        self.assertIn("WhatsApp text message", system)
        self.assertNotIn("SPOKEN", system)
        self.assertIn("Tuesday 22 September 2026, 09:05", system)
        self.assertTrue(system.endswith("SNAP\n\nFOCUS"))
        self.assertEqual([type(m).__name__ for m in msgs], ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"])
        self.assertEqual(msgs[1].content, "(voice note) hi")

    def test_reply_helpers(self):
        self.assertEqual(brain.reply_text(AIMessage("<think>hmm</think> Hello")), "Hello")
        self.assertEqual(brain.reply_text(AIMessage([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])), "ab")
        self.assertEqual(brain.split_reply("Say this.\n[[text]]\ngit push"), ("Say this.", "git push"))
        self.assertEqual(brain.split_reply("Only speech."), ("Only speech.", ""))
        self.assertEqual(brain.split_reply("Say.\n**[[TEXT]]**\ncode"), ("Say.", "code"))
        say, extra = brain.split_reply(LIVE_WRAPPED_REPLY)
        self.assertTrue(say.endswith("15-minute setup?"))
        self.assertTrue(extra.startswith("pip install APScheduler==3.10.4"))
        self.assertTrue(extra.endswith("scheduler.start()"))
        # The review's M2: only a trailing "[[" + line break block counts, and only in voice mode.
        for normal in ("Select columns with df[['name', 'age']] and then plot.", "See [[Project Ideas]] in your notes.",
                       "Talk. [[ unfinished"):
            self.assertEqual(brain.split_reply(normal), (normal, ""))
        self.assertEqual(brain.split_reply(LIVE_WRAPPED_REPLY, "text"), (LIVE_WRAPPED_REPLY, ""))

    def test_portfolio_refresh_is_one_scan_at_a_time(self):
        import threading
        calls, gate = [], threading.Event()

        def slow_discover(*a, **kw):
            calls.append(1)
            gate.wait(5)
            return [], []
        pf = brain.Portfolio(self.base, discover_fn=slow_discover)
        threads = [threading.Thread(target=pf.refresh, kwargs={"force": True}) for _ in range(3)]
        for t in threads:
            t.start()
        import time
        time.sleep(0.3)
        self.assertEqual(len(calls), 1)                   # the others wait instead of scanning alongside
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
