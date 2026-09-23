"""Scanner tests. Git-state checks compare against the real git CLI (skipped if git is absent).

    python -m unittest discover -s tests -t .
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from reminder import scan
from reminder.scan import DAY, discover, git_state, read_index, scan_project

HAS_GIT = shutil.which("git") is not None


def touch(path, content="x\n", age_days=0.0, now=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    t = (now or time.time()) - age_days * DAY
    os.utime(path, (t, t))


def truncated_v3_index():
    """A v3 index whose one entry claims extended flags and then simply stops."""
    entry = (b"\0" * 24 + struct.pack(">I", 0o100644) + b"\0" * 12 + b"\x11" * 20
             + struct.pack(">H", 0x4000))
    return b"DIRC" + struct.pack(">II", 3, 1) + entry


def broken_repo(path):
    """A .git that is present but unreadable, the two ways we have really seen."""
    g = os.path.join(path, ".git")
    os.makedirs(g, exist_ok=True)
    with open(os.path.join(g, "HEAD"), "wb") as fh:
        fh.write(b"ref: refs/heads/ma\xffin\n")             # not UTF-8
    with open(os.path.join(g, "index"), "wb") as fh:
        fh.write(truncated_v3_index())


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-scan-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class DiscoverTests(TempDirCase):
    def test_backup_copies_skipped_only_when_original_exists(self):
        for name in ("app", "app_backup_2026-09-15", "app_phase0_done", "app-copy", "tool_demo_live", "apple"):
            touch(os.path.join(self.tmp, name, "main.py"))
        projects, skipped = discover([self.tmp])
        names = sorted(p.name for p in projects)
        self.assertEqual(names, ["app", "apple", "tool_demo_live"])   # no "tool" sibling -> not a copy
        self.assertEqual(sorted(n for n, _ in skipped), ["app-copy", "app_backup_2026-09-15", "app_phase0_done"])

    def test_ignore_and_track_overrides(self):
        for name in ("app", "app_backup_1", "downloads"):
            touch(os.path.join(self.tmp, name, "f.txt"))
        projects, skipped = discover([self.tmp], ignore=["Downloads"], track=["app_backup_1"])
        self.assertEqual(sorted(p.name for p in projects), ["app", "app_backup_1"])
        self.assertIn(("downloads", "ignored"), skipped)

    def test_missing_root_raises_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            discover([os.path.join(self.tmp, "nope")])

    def test_dot_folders_are_not_projects(self):
        for name in ("app", ".hidden"):
            touch(os.path.join(self.tmp, name, "f.txt"))
        projects, skipped = discover([self.tmp])
        self.assertEqual([p.name for p in projects], ["app"])
        self.assertIn((".hidden", "ignored"), skipped)

    def test_one_unreadable_repo_does_not_stop_the_scan(self):
        for name in ("aaa", "bad", "zzz"):
            touch(os.path.join(self.tmp, name, "f.txt"))
        broken_repo(os.path.join(self.tmp, "bad"))
        projects, _ = discover([self.tmp])
        self.assertEqual(sorted(p.name for p in projects), ["aaa", "bad", "zzz"])
        bad = next(p for p in projects if p.name == "bad")
        self.assertIsNotNone(bad.git)                       # junk bytes read, not raised on
        self.assertIsNone(bad.git.modified)                 # truncated index: unknown

    def test_failing_project_is_logged_and_still_reported(self):
        for name in ("good", "sick"):
            touch(os.path.join(self.tmp, name, "f.txt"))

        def boom(project_dir):
            if project_dir.endswith("sick"):
                raise RuntimeError("disk said no")
            return None

        with mock.patch.object(scan, "git_state", boom), \
                self.assertLogs("reminder.scan", level="WARNING") as logged:
            projects, skipped = discover([self.tmp])
        sick = next(p for p in projects if p.name == "sick")
        self.assertEqual(sorted(p.name for p in projects), ["good", "sick"])
        self.assertIsNone(sick.git)
        self.assertIn("disk said no", sick.extra["error"])
        self.assertTrue(any("sick" in line for line in logged.output))
        self.assertEqual(skipped, [])

    def test_project_that_cannot_be_built_at_all_is_skipped(self):
        for name in ("good", "sick"):
            touch(os.path.join(self.tmp, name, "f.txt"))
        real_walk = scan._walk

        def boom(project_dir):
            if project_dir.endswith("sick"):
                raise OSError("gone")
            return real_walk(project_dir)

        with mock.patch.object(scan, "_walk", boom), self.assertLogs("reminder.scan", "WARNING"):
            projects, skipped = discover([self.tmp])
        self.assertEqual([p.name for p in projects], ["good"])
        self.assertIn(("sick", "unreadable: OSError"), skipped)


class ActivityTests(TempDirCase):
    def test_runtime_and_ignored_files_do_not_count_as_work(self):
        now = time.time()
        p = os.path.join(self.tmp, "proj")
        touch(os.path.join(p, "src", "main.py"), age_days=10, now=now)
        touch(os.path.join(p, ".gitignore"), "*.csv\n/out\nsecrets\n", age_days=10, now=now)
        for rel in ("data/app.db", "data/app.db-wal", "logs/run.log", ".env", "report.csv", "out/x.txt",
                    "secrets/k.txt", "node_modules/pkg/index.js", ".venv/lib/a.py", "__pycache__/m.pyc"):
            touch(os.path.join(p, *rel.split("/")), age_days=0, now=now)
        proj = scan_project(p, now=now)
        self.assertEqual(proj.idle_days, 10)
        self.assertEqual(sorted(proj.recent_files), [".gitignore", "src/main.py"])

    def test_todos_counted_once_on_case_insensitive_filesystems(self):
        p = os.path.join(self.tmp, "proj")
        touch(os.path.join(p, "README.md"), "# **My App**\n- [ ] first **thing**\n- [x] done\n* [ ] second\n")
        touch(os.path.join(p, "TODO.md"), "- [ ] third\n")
        proj = scan_project(p)
        self.assertEqual(proj.open_todos, 3)
        self.assertEqual(proj.todo_samples, ["first thing", "second", "third"])
        self.assertEqual(proj.readme_title, "My App")

    def test_empty_project_is_very_idle_not_a_crash(self):
        os.makedirs(os.path.join(self.tmp, "empty"))
        proj = scan_project(os.path.join(self.tmp, "empty"))
        self.assertGreater(proj.idle_days, 10000)
        self.assertIsNone(proj.git)

    def test_garbage_index_is_unknown_not_a_crash(self):
        g = os.path.join(self.tmp, ".git")
        os.makedirs(g)
        with open(os.path.join(g, "index"), "wb") as fh:
            fh.write(b"DIRC\x00\x00\x00\x02\x00\x00\x00\x05short")
        self.assertIsNone(read_index(g))

    def test_truncated_v3_index_with_extended_flag_is_unknown(self):
        g = os.path.join(self.tmp, ".git")
        os.makedirs(g)
        with open(os.path.join(g, "index"), "wb") as fh:
            fh.write(truncated_v3_index())
        self.assertIsNone(read_index(g))                   # not a struct.error

    def test_future_file_dates_do_not_count_as_work(self):
        now = time.time()
        p = os.path.join(self.tmp, "proj")
        touch(os.path.join(p, "old.py"), age_days=30, now=now)
        touch(os.path.join(p, "from_the_future.py"), age_days=-90, now=now)
        proj = scan_project(p, now=now)
        self.assertLessEqual(proj.last_work, now)          # a bad clock is not work done later
        self.assertEqual(proj.idle_days, 0)

    def test_symlinks_are_not_followed(self):
        now = time.time()
        p = os.path.join(self.tmp, "proj")
        touch(os.path.join(p, "old.py"), age_days=30, now=now)
        touch(os.path.join(self.tmp, "outside", "fresh.py"), age_days=0, now=now)
        try:
            os.symlink(os.path.join(self.tmp, "outside", "fresh.py"), os.path.join(p, "link.py"))
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here: {exc}")
        proj = scan_project(p, now=now)
        self.assertEqual(proj.recent_files, ["old.py"])
        self.assertEqual(proj.idle_days, 30)


@unittest.skipUnless(HAS_GIT, "git not installed")
class GitOracleTests(TempDirCase):
    """Every expectation here comes from the real git CLI, not from hand-written values."""

    # Unmerged codes from `git status --porcelain`. We report a conflicted path as
    # modified: its working copy holds conflict markers, so it is never "clean".
    CONFLICT = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

    def run_git(self, cwd, *args, env=None):
        run_env = None if env is None else {**os.environ, **env}
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=run_env)

    def git(self, cwd, *args, env=None):
        r = self.run_git(cwd, *args, env=env)
        if r.returncode:
            raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
        return r.stdout

    def oracle(self, repo):
        out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True,
                             text=True).stdout
        tracked = sorted(l[3:] for l in out.splitlines() if l and not l.startswith("??") and
                         (l[:2] in self.CONFLICT or any(c in l[:2] for c in "MD")))
        try:
            unpushed = int(self.git(repo, "rev-list", "--count", "@{u}..HEAD").strip())
        except subprocess.CalledProcessError:
            unpushed = None
        return tracked, unpushed

    def index_oracle(self, repo):
        """Paths git keeps in the index as plain files -- what read_index should list.
        Only valid where nothing is flagged assume-valid or skip-worktree."""
        out = self.git(repo, "ls-files", "--stage")
        rows = [(l.split(" ", 1)[0], l.split()[2], l.split("\t", 1)[1]) for l in out.splitlines()]
        return sorted(path for mode, stage, path in rows if mode in ("100644", "100755") and stage == "0")

    def assertMatchesGit(self, repo):
        tracked, unpushed = self.oracle(repo)
        st = git_state(repo)
        self.assertEqual(sorted(st.modified), tracked)
        if unpushed is not None:
            self.assertEqual(st.unpushed, unpushed)

    def commit(self, repo, name, body="x\n"):
        touch(os.path.join(repo, name), body)
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", name)
        return self.git(repo, "rev-parse", "HEAD").strip()

    def clone(self, bare, name):
        repo = os.path.join(self.tmp, name)
        self.git(self.tmp, "clone", bare, repo)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            self.git(repo, "config", k, v)
        return repo

    def solo_repo(self, name, *init_args):
        repo = os.path.join(self.tmp, name)
        os.makedirs(repo)
        self.git(repo, "init", *init_args, "-b", "main")
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            self.git(repo, "config", k, v)
        return repo

    def make_repo(self):
        bare = os.path.join(self.tmp, "origin.git")
        a = os.path.join(self.tmp, "a")
        self.git(self.tmp, "init", "--bare", "-b", "main", bare)
        self.git(self.tmp, "clone", bare, a)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("core.autocrlf", "true")):
            self.git(a, "config", k, v)
        touch(os.path.join(a, "lf.txt"), "one\ntwo\n")
        touch(os.path.join(a, "crlf.txt"), "x\r\ny\r\n")
        touch(os.path.join(a, "gone.txt"), "bye\n")
        with open(os.path.join(a, "bin.dat"), "wb") as fh:
            fh.write(bytes([0, 1, 2, 13, 10, 255]))
        self.git(a, "add", ".")
        self.git(a, "commit", "-m", "initial")
        self.git(a, "push", "-u", "origin", "main")
        return bare, a

    def test_clean_touched_edited_ahead_behind(self):
        bare, a = self.make_repo()
        self.assertMatchesGit(a)                                        # clean after push
        st = git_state(a)
        self.assertEqual((st.branch, st.has_remote, st.recent_commits), ("main", True, ["initial"]))

        later = time.time() + 5                                         # stat changes, content doesn't
        for f in ("lf.txt", "crlf.txt"):
            os.utime(os.path.join(a, f), (later, later))
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).modified, [])

        touch(os.path.join(a, "lf.txt"), "one\nTWO\n")                  # real edit + deletion + untracked
        os.remove(os.path.join(a, "gone.txt"))
        touch(os.path.join(a, "untracked.txt"), "new\n")
        self.assertMatchesGit(a)
        self.assertEqual(sorted(git_state(a).modified), ["gone.txt", "lf.txt"])

        self.git(a, "add", "-A")                                        # two local commits
        self.git(a, "commit", "-m", "local 1")
        touch(os.path.join(a, "more.txt"), "m\n")
        self.git(a, "add", ".")
        self.git(a, "commit", "-m", "local 2")
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).unpushed, 2)
        self.assertEqual(git_state(a).recent_commits[:2], ["local 2", "local 1"])

        self.git(a, "push")                                             # behind origin is not "unpushed"
        b = os.path.join(self.tmp, "b")
        self.git(self.tmp, "clone", bare, b)
        self.git(b, "config", "user.email", "t@t")
        self.git(b, "config", "user.name", "t")
        touch(os.path.join(b, "remote.txt"), "r\n")
        self.git(b, "add", ".")
        self.git(b, "commit", "-m", "from b")
        self.git(b, "push")
        self.git(a, "fetch")
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).unpushed, 0)

    def test_no_remote_means_unpushed_unknown(self):
        repo = os.path.join(self.tmp, "solo")
        os.makedirs(repo)
        self.git(repo, "init", "-b", "main")
        self.git(repo, "config", "user.email", "t@t")
        self.git(repo, "config", "user.name", "t")
        touch(os.path.join(repo, "a.txt"))
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "first")
        st = git_state(repo)
        self.assertFalse(st.has_remote)
        self.assertIsNone(st.unpushed)
        self.assertEqual(st.modified, [])

    # ----------------------------------------------------------------- modified files

    def test_crlf_normalisation_survives_a_stat_only_touch(self):
        # git_state runs BEFORE any git command here on purpose: `git status`
        # refreshes the index stat data, which hides a missing autocrlf fold.
        bare, a = self.make_repo()
        later = time.time() + 5
        os.utime(os.path.join(a, "crlf.txt"), (later, later))
        self.assertEqual(git_state(a).modified, [])
        self.assertMatchesGit(a)                            # and git agrees

    def test_skip_worktree_and_assume_unchanged_are_not_modified(self):
        repo = self.solo_repo("flags")
        for name in ("a.txt", "b.txt", "c.txt"):
            touch(os.path.join(repo, name), "start\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "c")
        self.git(repo, "update-index", "--skip-worktree", "a.txt")    # index v3 extended flags
        self.git(repo, "update-index", "--assume-unchanged", "b.txt")
        for name in ("a.txt", "b.txt", "c.txt"):
            touch(os.path.join(repo, name), "edited\n")
        self.assertEqual(self.oracle(repo)[0], ["c.txt"])   # git ignores the flagged two
        self.assertEqual(git_state(repo).modified, ["c.txt"])

    def test_index_entry_padding_matches_git(self):
        repo = self.solo_repo("padding")
        touch(os.path.join(repo, "ab"), "a\n")              # len 2: entry pads by a full 8 bytes
        touch(os.path.join(repo, "zz.txt"), "z\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "c")
        self.assertEqual(sorted(n for n, *_ in read_index(os.path.join(repo, ".git"))),
                         self.index_oracle(repo))
        touch(os.path.join(repo, "zz.txt"), "edited\n")     # the entry after the padded one
        self.assertMatchesGit(repo)

    def test_gitlinks_are_not_tracked_files(self):
        bare, _ = self.make_repo()
        repo = self.solo_repo("withsub")
        self.commit(repo, "f.txt")
        r = self.run_git(repo, "-c", "protocol.file.allow=always", "submodule", "add",
                         bare.replace("\\", "/"), "sub")
        if r.returncode:
            self.skipTest("submodule add unavailable: " + r.stderr.strip()[:120])
        self.git(repo, "commit", "-m", "add submodule")
        self.assertIn("sub", self.git(repo, "ls-files", "--stage"))   # git tracks it, mode 160000
        self.assertEqual(sorted(n for n, *_ in read_index(os.path.join(repo, ".git"))),
                         self.index_oracle(repo))           # ...but not as a file
        self.assertMatchesGit(repo)

    def test_symlinks_are_not_tracked_files(self):
        repo = self.solo_repo("links")
        touch(os.path.join(repo, "f.txt"), "content\n")
        try:
            os.symlink(os.path.join(repo, "f.txt"), os.path.join(repo, "lnk"))
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlinks here: {exc}")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "c")
        self.assertEqual(sorted(n for n, *_ in read_index(os.path.join(repo, ".git"))),
                         self.index_oracle(repo))
        self.assertMatchesGit(repo)

    def test_merge_conflict_paths_are_reported_modified(self):
        repo = self.solo_repo("conflict")
        self.commit(repo, "f.txt", "base\n")
        self.git(repo, "checkout", "-b", "feat")
        self.commit(repo, "f.txt", "feat\n")
        self.git(repo, "checkout", "main")
        self.commit(repo, "f.txt", "main\n")
        self.assertNotEqual(self.run_git(repo, "merge", "feat").returncode, 0)   # left unresolved
        self.assertIn("UU", self.git(repo, "status", "--porcelain"))
        self.assertMatchesGit(repo)                         # a conflict is never "clean"
        self.assertEqual(git_state(repo).modified, ["f.txt"])

    def test_files_over_the_hash_limit_are_hashed_not_assumed_modified(self):
        bare, a = self.make_repo()
        later = time.time() + 5
        os.utime(os.path.join(a, "lf.txt"), (later, later))  # stat moved, content did not
        with mock.patch.object(scan, "MAX_HASH_BYTES", 4):   # pretend it is a huge file
            st = git_state(a)
        self.assertEqual(st.modified, [])
        self.assertEqual(self.oracle(a)[0], [])

    def test_max_hashes_flags_a_partial_answer(self):
        bare, a = self.make_repo()
        for name in ("bin.dat", "crlf.txt", "lf.txt"):
            touch(os.path.join(a, name), "edited " + name + "\n")
        with mock.patch.object(scan, "MAX_HASHES", 1):
            st = git_state(a)
        self.assertTrue(st.modified_partial)
        self.assertLess(len(st.modified), len(self.oracle(a)[0]))
        self.assertFalse(git_state(a).modified_partial)     # unlimited: a complete answer

    def test_modified_newest_is_the_newest_edited_file(self):
        bare, a = self.make_repo()
        now = time.time()
        touch(os.path.join(a, "lf.txt"), "edited\n", age_days=5, now=now)
        touch(os.path.join(a, "crlf.txt"), "edited too\n", age_days=1, now=now)
        st = git_state(a)
        self.assertEqual(sorted(st.modified), ["crlf.txt", "lf.txt"])
        self.assertEqual(st.modified_newest, os.stat(os.path.join(a, "crlf.txt")).st_mtime)

    # ----------------------------------------------------------------- unpushed commits

    def test_merge_revert_and_cherry_pick_count_as_unpushed(self):
        bare, a = self.make_repo()
        self.git(a, "checkout", "-b", "feat")
        self.commit(a, "feat.txt", "f\n")
        self.git(a, "checkout", "main")
        self.git(a, "merge", "--ff-only", "feat")           # reflog: "merge feat: Fast-forward"
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).unpushed, 1)

        self.git(a, "checkout", "-b", "side")
        pick = self.commit(a, "side.txt", "s\n")
        self.git(a, "checkout", "main")
        self.git(a, "revert", "--no-edit", "HEAD")          # reflog: "revert: ..."
        self.assertMatchesGit(a)
        self.git(a, "cherry-pick", pick)                    # reflog: "cherry-pick: ..."
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).unpushed, 3)

    def test_amend_and_reset_do_not_over_count(self):
        bare, a = self.make_repo()
        self.commit(a, "one.txt")
        self.commit(a, "two.txt")
        self.git(a, "commit", "--amend", "-m", "two amended")
        self.assertMatchesGit(a)                            # 2 commits, 3 reflog entries
        self.git(a, "reset", "--hard", "HEAD~1")
        self.assertMatchesGit(a)                            # 1 commit, 4 reflog entries

    def test_squash_rebase_matches_git(self):
        bare, a = self.make_repo()
        for name in ("c1.txt", "c2.txt", "c3.txt"):
            self.commit(a, name)
        editor = os.path.join(self.tmp, "squash.py")
        with open(editor, "w", encoding="utf-8") as fh:
            fh.write("import sys\n"
                     "p = sys.argv[1]\n"
                     "out, n = [], 0\n"
                     "for line in open(p, encoding='utf-8').read().splitlines():\n"
                     "    if line.startswith('pick '):\n"
                     "        n += 1\n"
                     "        line = line if n == 1 else 'squash ' + line[5:]\n"
                     "    out.append(line)\n"
                     "open(p, 'w', encoding='utf-8').write('\\n'.join(out) + '\\n')\n")
        self.git(a, "rebase", "-i", "HEAD~3",
                 env={"GIT_SEQUENCE_EDITOR": f'"{sys.executable}" "{editor}"', "GIT_EDITOR": "true"})
        self.assertMatchesGit(a)
        self.assertEqual(git_state(a).unpushed, 1)          # four reflog entries, one commit

    def test_clone_then_commit_without_any_fetch(self):
        bare, a = self.make_repo()
        c = self.clone(bare, "c")
        # git writes no remote-tracking reflog on clone: the ref file is all there is.
        self.assertFalse(os.path.exists(os.path.join(c, ".git", "logs", "refs", "remotes",
                                                     "origin", "main")))
        self.commit(c, "local.txt")
        self.assertMatchesGit(c)
        self.assertEqual(git_state(c).unpushed, 1)

    def test_clone_from_a_packed_origin_then_commit(self):
        # As above, but origin's history arrives packed (a clone hardlinks whatever
        # origin has), so no commit walk is possible and the remote *ref* is the
        # only record of what origin holds.
        bare, a = self.make_repo()
        self.git(bare, "gc", "--quiet", "--prune=now")
        c = self.clone(bare, "packed-clone")
        self.assertFalse(os.path.exists(os.path.join(c, ".git", "logs", "refs", "remotes",
                                                     "origin", "main")))
        self.commit(c, "local.txt")
        self.assertMatchesGit(c)
        self.assertEqual(git_state(c).unpushed, 1)

    def test_packed_objects_and_refs_fall_back_to_the_reflog(self):
        bare, a = self.make_repo()
        c = self.clone(bare, "packed")
        self.git(c, "checkout", "-b", "feat")
        self.commit(c, "feat.txt", "f\n")
        self.git(c, "checkout", "main")
        self.git(c, "merge", "--ff-only", "feat")
        self.git(c, "gc", "--quiet", "--prune=now")         # nothing loose, refs packed away
        self.assertFalse(os.path.exists(os.path.join(c, ".git", "refs", "heads", "main")))
        self.assertMatchesGit(c)
        self.assertEqual(git_state(c).unpushed, 1)

    def test_behind_origin_after_fetch_and_gc_is_not_unpushed(self):
        bare, a = self.make_repo()
        c = self.clone(bare, "behind")
        self.commit(a, "ahead.txt")
        self.git(a, "push")
        self.git(c, "fetch")                                # origin/main moves, main does not
        self.git(c, "gc", "--quiet", "--prune=now")         # ...and nothing stays loose
        self.assertMatchesGit(c)
        self.assertEqual(git_state(c).unpushed, 0)

    # ----------------------------------------------------------------- repo layouts

    def test_linked_worktree_is_followed(self):
        bare, a = self.make_repo()
        wt = os.path.join(self.tmp, "wt")
        self.git(a, "worktree", "add", "-b", "wtbr", wt)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".git")))     # a file, not a folder
        touch(os.path.join(wt, "lf.txt"), "one\nCHANGED\n")
        st = git_state(wt)
        self.assertIsNotNone(st)
        self.assertEqual(st.branch, "wtbr")
        self.assertEqual(st.modified, ["lf.txt"])
        self.assertMatchesGit(wt)

    def test_sha256_repo_is_unknown_not_clean(self):
        repo = os.path.join(self.tmp, "s256")
        os.makedirs(repo)
        if self.run_git(repo, "init", "--object-format=sha256", "-b", "main").returncode:
            self.skipTest("git without sha256 object format")
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            self.git(repo, "config", k, v)
        self.commit(repo, "f.txt")
        later = time.time() + 5
        os.utime(os.path.join(repo, "f.txt"), (later, later))          # defeat the stat fast path
        st = git_state(repo)
        self.assertEqual(self.oracle(repo)[0], [])                     # git: nothing modified
        self.assertIsNone(st.modified)                                 # us: unknown, not a guess

    def test_split_index_is_unknown(self):
        repo = self.solo_repo("split")
        self.commit(repo, "f.txt")
        if self.run_git(repo, "update-index", "--split-index").returncode:
            self.skipTest("git without split-index support")
        self.assertTrue(any(n.startswith("sharedindex")
                            for n in os.listdir(os.path.join(repo, ".git"))))
        self.assertIsNone(git_state(repo).modified)


if __name__ == "__main__":
    unittest.main()
