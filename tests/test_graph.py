"""Workflow + investigator agent tests with a fake chat model (no network).

    .venv\\Scripts\\python.exe -m unittest tests.test_graph -v
"""
import itertools
import os
import shutil
import tempfile
import unittest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from reminder import graph, tools
from reminder.remind import Config, Flagged, Verdict
from reminder.scan import GitState, Project, scan_project


def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}", "type": "tool_call"}])


class FakeLLM(GenericFakeChatModel):
    """Replays scripted AI messages; structured output returns a fixed verdict and records
    the transcript it was given."""
    verdict: dict = {}
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def make(msgs):
            self.seen.append(list(msgs))
            return schema(**self.verdict)
        return RunnableLambda(make)


VERDICT = {"status": "unfinished", "left_off": "Auth done, scheduler missing.", "next_step": "Wire the scheduler in app.py.",
           "confidence": 0.8, "evidence": ["README.md: - [ ] scheduler"]}


class TempProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-graph-")
        self.proj = os.path.join(self.tmp, "app")
        self.write("README.md", "# App\n- [x] auth\n- [ ] wire the scheduler\n")
        self.write("app.py", "API_KEY = 'sk-live-123'\nPASSWORD: hunter2\ndef main():\n    pass\n")
        self.write(".env", "SECRET=1\n")
        self.write("key.pem", "-----BEGIN\n")
        self.write("node_modules/x/index.js", "x")
        with open(os.path.join(self.proj, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02text")
        self.project = scan_project(self.proj)
        self.tools = tools.make_tools(self.project)
        self.by_name = {t.name: t for t in self.tools}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, content):
        p = os.path.join(self.proj, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)


class ToolTests(TempProject):
    def test_schema_keeps_real_signatures(self):
        self.assertEqual(set(self.by_name["read_file"].args), {"path", "start_line", "max_lines"})
        self.assertEqual(set(self.by_name["list_files"].args), {"subdir"})
        self.assertEqual(set(self.by_name["git_summary"].args), set())

    def test_read_file_numbers_lines_and_redacts_secrets(self):
        out = self.by_name["read_file"].invoke({"path": "app.py"})
        self.assertIn("    1: API_KEY = [redacted]", out)
        self.assertIn("PASSWORD: [redacted]", out)
        self.assertIn("def main", out)

    def test_refuses_outside_secret_and_binary(self):
        outside = self.by_name["read_file"].invoke({"path": "../../" + os.path.basename(self.tmp)})
        self.assertTrue(outside.startswith("Refused"), outside)
        self.assertTrue(self.by_name["read_file"].invoke({"path": "..\\other\\x.txt"}).startswith("Refused"))
        # "..\app\README.md" lands back inside the project, so it is allowed.
        self.assertIn("wire the scheduler", self.by_name["read_file"].invoke({"path": "..\\app\\README.md"}))
        for p in (".env", "key.pem", "blob.bin"):
            self.assertTrue(self.by_name["read_file"].invoke({"path": p}).startswith("Refused"), p)
        self.assertTrue(self.by_name["read_file"].invoke({"path": "missing.py"}).startswith("Refused"))

    def test_list_hides_secrets_and_dependency_folders(self):
        out = self.by_name["list_files"].invoke({"subdir": ""})
        self.assertIn("README.md", out)
        self.assertIn("app.py", out)
        for hidden in (".env", "key.pem", "node_modules"):
            self.assertNotIn(hidden, out)
        self.assertTrue(self.by_name["list_files"].invoke({"subdir": "nope"}).startswith("Refused"))

    def test_sandbox_blocks_real_files_outside_the_project(self):
        with open(os.path.join(self.tmp, "outside.txt"), "w") as fh:
            fh.write("OUTSIDE_MARKER_42\n")
        self.assertTrue(self.by_name["read_file"].invoke({"path": "../outside.txt"}).startswith("Refused"))
        self.assertTrue(self.by_name["read_file"].invoke({"path": os.path.join(self.tmp, "outside.txt")}).startswith("Refused"))
        self.assertTrue(self.by_name["list_files"].invoke({"subdir": ".."}).startswith("Refused"))
        self.assertEqual(self.by_name["search_files"].invoke({"pattern": "OUTSIDE_MARKER_42"}), "No matches.")

    def test_junction_cannot_lead_outside(self):
        import subprocess
        outside = os.path.join(self.tmp, "OUTSIDE")
        os.makedirs(outside)
        with open(os.path.join(outside, "loot.txt"), "w") as fh:
            fh.write("JUNCTION_MARKER_77\n")
        link = os.path.join(self.proj, "docs")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, outside], capture_output=True)
        if r.returncode != 0 or not os.path.isdir(link):
            self.skipTest("cannot create a directory junction here")
        self.assertEqual(self.by_name["search_files"].invoke({"pattern": "JUNCTION_MARKER_77"}), "No matches.")
        self.assertTrue(self.by_name["read_file"].invoke({"path": "docs/loot.txt"}).startswith("Refused"))
        self.assertTrue(self.by_name["list_files"].invoke({"subdir": "docs"}).startswith("Refused"))

    def test_hard_link_is_refused(self):
        outside = os.path.join(self.tmp, "hl.txt")
        with open(outside, "w") as fh:
            fh.write("HARDLINK_MARKER_9\n")
        try:
            os.link(outside, os.path.join(self.proj, "hl.txt"))
        except OSError:
            self.skipTest("cannot create a hard link here")
        self.assertTrue(self.by_name["read_file"].invoke({"path": "hl.txt"}).startswith("Refused"))
        self.assertEqual(self.by_name["search_files"].invoke({"pattern": "HARDLINK_MARKER_9"}), "No matches.")

    def test_search_skips_secret_files_and_dependency_folders(self):
        self.write(".env", "SECRET_TOKEN_VALUE_XYZ\n")
        self.write("node_modules/pkg/index.js", "DEP_MARKER_55\n")
        self.assertEqual(self.by_name["search_files"].invoke({"pattern": "SECRET_TOKEN_VALUE_XYZ"}), "No matches.")
        self.assertEqual(self.by_name["search_files"].invoke({"pattern": "DEP_MARKER_55"}), "No matches.")

    def test_redaction_formats(self):
        r = tools.redact
        self.assertEqual(r('{"api_key": "sk-live-1", "x": 1}'), '{"api_key": [redacted]')
        self.assertEqual(r("DATABASE_URL=postgres://user:P4ss@host/db"), "DATABASE_URL=postgres://user:[redacted]@host/db")
        self.assertEqual(r("Authorization: Bearer eyJ.abc"), "Authorization: [redacted]")
        self.assertEqual(r("api_key = " + "A" * 300 + "TAIL"), "api_key = [redacted]")
        self.assertEqual(r("-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\nafter"), "[redacted key block]\nafter")
        self.assertEqual(r("x\n-----BEGIN RSA PRIVATE KEY-----\nMIIE (chunk ends)"), "x\n[redacted key block]")
        self.assertEqual(r("accessToken: abc"), "accessToken: [redacted]")
        self.assertEqual(r("db.password = x"), "db.password = [redacted]")
        for harmless in ("monkey = 1", "keyboard: qwerty", "turkey = 3", "def main():"):
            self.assertEqual(r(harmless), harmless)

    def test_more_secret_shapes_are_caught(self):
        r = tools.redact
        for line, key in (("DB_PASS=hunter2", "DB_PASS="), ("PGPASSWORD=hunter2", "PGPASSWORD="),
                          ("STRIPE_SK: abc123", "STRIPE_SK: "), ("MYSQL_ROOTPASSWORD = x", "MYSQL_ROOTPASSWORD = ")):
            self.assertEqual(r(line), key + "[redacted]", line)
        key = "gsk_" + "a1B2" * 12
        self.assertEqual(r(f'client = Groq("{key}")'), 'client = Groq("[redacted]")')
        self.assertEqual(r("token EAA" + "x" * 60 + " end"), "token [redacted] end")
        stripe = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
        self.assertEqual(r(f"stripe.api_base_key('{stripe}')"), "stripe.api_base_key('[redacted]')")
        self.assertEqual(r("define('DB_PASSWORD', 'hunter2');"), "define('DB_PASSWORD', '[redacted]');")
        self.assertEqual(r('os.environ.setdefault("API_KEY", "abc123")'), 'os.environ.setdefault("API_KEY", "[redacted]")')
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        self.assertEqual(r(f"anon: '{jwt}'".replace("anon: ", "x = ")), "x = '[redacted]'")
        for harmless in ("max_tokens = 5", "tokenizer = load()", "compass = 3", "task = run()", "skip = True"):
            self.assertEqual(r(harmless), harmless)
        for name in ("prod.env", ".env-local", ".env_backup", ".envrc", "secrets.env", ".pgpass", ".netrc", ".npmrc"):
            self.assertTrue(tools.SECRET_FILE.search(name), name)
        for name in ("environment.py", "venv.md", "envelope.txt", "README.md"):
            self.assertFalse(tools.SECRET_FILE.search(name), name)

    def test_search_and_git_summary(self):
        out = self.by_name["search_files"].invoke({"pattern": r"\[ \]"})
        self.assertIn("README.md:3:", out)
        self.assertNotIn("hunter2", self.by_name["search_files"].invoke({"pattern": "PASSWORD"}))
        self.assertTrue(self.by_name["search_files"].invoke({"pattern": "("}).startswith("Refused"))
        self.assertIn("not a git repository", self.by_name["git_summary"].invoke({}))

    def test_output_is_capped(self):
        self.write("many.txt", "\n".join(f"l{i}" for i in range(500)))
        out = self.by_name["read_file"].invoke({"path": "many.txt", "max_lines": 500})
        self.assertIn("  120: l119", out)                              # capped at MAX_LINES
        self.assertNotIn("  121:", out)
        self.assertIn("380 more lines", out)
        self.write("wide.txt", "\n".join("x" * 200 for _ in range(100)))
        out = self.by_name["read_file"].invoke({"path": "wide.txt"})
        self.assertLessEqual(len(out), tools.MAX_TOOL_CHARS + 200)     # capped at MAX_TOOL_CHARS
        self.assertIn("truncated", out)


class InvestigatorTests(TempProject):
    def flagged(self):
        return Flagged(self.project, True, [])

    def test_loop_calls_tool_then_returns_structured_verdict(self):
        llm = FakeLLM(messages=iter([tool_call("read_file", path="README.md"), AIMessage(content="I know enough.")]),
                      verdict=VERDICT, seen=[])
        g = graph.build_investigator(llm, self.tools, pacer=graph.TokenPacer(clock=lambda: 0, sleep=lambda s: None))
        res = g.invoke({"messages": [SystemMessage("sys"), HumanMessage("facts")], "verdict": None})
        tool_msgs = [m for m in res["messages"] if isinstance(m, ToolMessage)]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("wire the scheduler", tool_msgs[0].content)
        self.assertEqual(res["verdict"]["status"], "unfinished")
        self.assertIsInstance(llm.seen[0][-1], HumanMessage)          # verdict prompt appended last

    def test_tool_budget_forces_a_verdict(self):
        # Fresh message objects each turn: LangGraph merges messages that share an id.
        llm = FakeLLM(messages=(tool_call("list_files", subdir="") for _ in itertools.count()), verdict=VERDICT, seen=[])
        g = graph.build_investigator(llm, self.tools, max_tool_calls=3,
                                     pacer=graph.TokenPacer(clock=lambda: 0, sleep=lambda s: None))
        res = g.invoke({"messages": [HumanMessage("facts")], "verdict": None}, config={"recursion_limit": 40})
        self.assertEqual(sum(isinstance(m, ToolMessage) for m in res["messages"]), 3)
        transcript = llm.seen[0]
        self.assertFalse(getattr(transcript[-2], "tool_calls", None), "dangling tool call left before verdict")

    def test_investigate_projects_converts_and_traces(self):
        llm = FakeLLM(messages=iter([tool_call("read_file", path="README.md"), AIMessage(content="done")]),
                      verdict={**VERDICT, "left_off": " spaced\n out ", "next_step": "x" * 300,
                               "evidence": ["a", "b", "c"]}, seen=[])
        cfg = Config(path="x", projects_roots=[self.tmp])
        out = graph.investigate_projects([self.flagged()], cfg, {}, llm=llm)
        v = out["app"]
        self.assertIsInstance(v, Verdict)
        self.assertEqual((v.source, v.left_off, v.evidence), ("agent", "spaced out", ["a", "b", "c"]))
        self.assertEqual(len(v.next_step), 160)                          # clipped for the WhatsApp variable
        self.assertEqual(v.trace, ["read_file(path='README.md')"])

    def test_schema_rejects_oversized_or_invalid_verdicts(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            graph.VerdictModel(**{**VERDICT, "evidence": ["a", "b", "c", "d"]})
        with self.assertRaises(ValidationError):
            graph.VerdictModel(**{**VERDICT, "status": "maybe"})
        with self.assertRaises(ValidationError):
            graph.VerdictModel(**{**VERDICT, "confidence": 1.5})

    def test_invalid_status_from_model_becomes_unclear(self):
        class RawDictLLM(FakeLLM):
            def with_structured_output(self, schema, **kwargs):
                return RunnableLambda(lambda msgs: dict(self.verdict))     # bypasses pydantic validation
        llm = RawDictLLM(messages=iter([AIMessage(content="done")]), verdict={**VERDICT, "status": "maybe"}, seen=[])
        out = graph.investigate_projects([self.flagged()], Config(path="x", projects_roots=[self.tmp]), {}, llm=llm)
        self.assertEqual(out["app"].status, "unclear")

    def test_deadline_stops_investigating(self):
        llm = FakeLLM(messages=iter([AIMessage(content="done")]), verdict=VERDICT, seen=[])
        cfg = Config(path="x", projects_roots=[self.tmp])
        self.assertEqual(graph.investigate_projects([self.flagged()], cfg, {}, llm=llm, deadline=0), {})
        self.assertEqual(llm.seen, [])                                       # never even asked

    def test_agent_failure_leaves_project_on_fallback(self):
        class Boom(FakeLLM):
            def bind_tools(self, tools, **kw):
                raise RuntimeError("provider down")
        out = graph.investigate_projects([self.flagged()], Config(path="x", projects_roots=[self.tmp]), {},
                                         llm=Boom(messages=iter([])))
        self.assertEqual(out, {})

    def test_no_key_disables_agent_quietly(self):
        self.assertEqual(graph.investigate_projects([self.flagged()], Config(path="x", projects_roots=[self.tmp]),
                                                    {"GROQ_API_KEY": ""}), {})

    def test_project_facts_are_json_safe(self):
        import json
        p = Project(name="p", path="x", last_work=0, idle_days=5, files=1, truncated=False, recent_files=["a"],
                    readme_title="T", open_todos=1, todo_samples=["do"], git=GitState("main", True, 1, 0, ["c"], ["f"], False, 0))
        json.dumps(graph.project_facts(Flagged(p, True, ["r"]), Config(path="x", projects_roots=["."], notes={"p": "n"})))


class PacerTests(unittest.TestCase):
    def test_sleeps_only_when_window_is_full(self):
        clock, slept = [0.0], []

        def sleep(s):
            slept.append(s)
            clock[0] += s
        p = graph.TokenPacer(budget=1000, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(p.before(600), 0)
        p.after(600)
        clock[0] = 10
        self.assertEqual(p.before(300), 0)                              # 900 <= 1000
        p.after(300)
        self.assertGreater(p.before(300), 0)                            # would be 1200: wait for the first to age out
        self.assertGreaterEqual(clock[0], 60)
        self.assertEqual(p.before(300), 0)

    def test_oversized_call_waits_once_and_never_crashes(self):
        clock, slept = [0.0], []

        def sleep(s):
            slept.append(s)
            clock[0] += s
        p = graph.TokenPacer(budget=1000, clock=lambda: clock[0], sleep=sleep)
        p.after(900)
        clock[0] = 5
        self.assertGreater(p.before(5000), 0)                           # bigger than the budget: wait for an empty window
        self.assertEqual(len(slept), 1)
        p.after(5000)
        self.assertEqual(p.before(1), 0) if not p.events else None      # no IndexError on either path

    def test_deadline_raises_instead_of_sleeping_past_it(self):
        clock = [0.0]
        p = graph.TokenPacer(budget=1000, clock=lambda: clock[0], sleep=lambda s: None, deadline=30)
        p.after(900)
        with self.assertRaises(graph.RunDeadline):
            p.before(500)

    def test_tokens_used_prefers_provider_usage(self):
        msg = AIMessage(content="x", response_metadata={"token_usage": {"total_tokens": 321}})
        self.assertEqual(graph.tokens_used(msg, 5), 321)
        self.assertEqual(graph.tokens_used(AIMessage(content="x"), 5), 5)


if __name__ == "__main__":
    unittest.main()
