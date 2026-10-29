"""Discover projects under root folders and measure how cold they are.

Standard library only. Git state is read straight from each ``.git`` folder
(the index and the reflogs), so no git binary is needed:

* modified files match ``git status`` for tracked files (stat fast path, then
  blob SHA-1, tolerant of ``core.autocrlf`` line-ending conversion);
* unpushed commits match ``git rev-list --count @{u}..HEAD``: the commits
  reachable from the branch tip that ``origin/<branch>`` has never held, read
  from the loose commit objects that local work always is, with the branch
  reflog as a fallback once those have been packed away.

Layouts we cannot read exactly (index v4, split index, sha256 objects) report
``None`` -- "unknown" -- rather than a plausible wrong answer.

This module only *measures*. Deciding what counts as cold lives in remind.py.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import struct
import time
import zlib
from dataclasses import dataclass, field

log = logging.getLogger("reminder.scan")

PRUNE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode", ".gradle",
    ".terraform", "coverage", ".cache", ".parcel-cache", ".turbo", ".state",
}
# Files an app writes while running are not "work on the project".
RUNTIME_EXT = re.compile(r"\.(db|sqlite3?|db-wal|db-shm|db-journal|log|pyc|pyo|tmp|swp|pid)$", re.I)
RUNTIME_NAME = re.compile(r"^(\.env(\..+)?|\.DS_Store|Thumbs\.db|desktop\.ini|.+\.tsbuildinfo)$", re.I)
# "soc-agents_backup_2026-09-15" is a copy of "soc-agents" when that sibling exists.
COPY_RE = re.compile(r"^(.+?)[_ -](backup|checkpoint|copy|phase|pre|demo|old|bak)(?![a-z])", re.I)
TODO_RE = re.compile(r"^\s*[-*] \[ \]\s+(.+?)\s*$", re.M)
TODO_FILES = ("readme.md", "todo.md", "next.md")   # lower-case; matched case-insensitively
MAX_FILES = 20000
MAX_HASHES = 3000
MAX_HASH_BYTES = 20 * 1024 * 1024        # read whole below this, hash in chunks above
HUGE_HASH_BYTES = 200 * 1024 * 1024      # above this, reading the file would stall the scan
MAX_WALK = 500                           # commits to read per repo when counting unpushed
DAY = 86400.0


@dataclass
class GitState:
    branch: str | None
    has_remote: bool
    unpushed: int | None            # None = could not determine
    last_commit: float              # epoch seconds, 0 if none
    recent_commits: list[str]
    modified: list[str] | None      # None = index unreadable (v4, split index, sha256)
    modified_partial: bool
    modified_newest: float          # newest mtime among modified files, 0 if none


@dataclass
class Project:
    name: str
    path: str
    last_work: float                # epoch seconds
    idle_days: int
    files: int
    truncated: bool
    recent_files: list[str]
    readme_title: str
    open_todos: int
    todo_samples: list[str]
    git: GitState | None = None
    skipped_copy_of: str | None = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- ignore rules

def _load_gitignore(project_dir: str):
    names, exts, anchored = set(), [], []
    try:
        with open(os.path.join(project_dir, ".gitignore"), encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        line = line.strip()
        if not line or line[0] in "#!":
            continue
        line = line.rstrip("/")
        if re.fullmatch(r"\*\.[\w.-]+", line):
            exts.append(line[1:].lower())
        elif line.startswith("/"):
            anchored.append(line[1:])
        elif not re.search(r"[*?\[/]", line):
            names.add(line)
    return names, exts, anchored


def _ignored(rules, rel: str, name: str) -> bool:
    if RUNTIME_EXT.search(name) or RUNTIME_NAME.match(name):
        return True
    names, exts, anchored = rules
    if name in names:
        return True
    lower = name.lower()
    if any(lower.endswith(e) for e in exts):
        return True
    rel = rel.replace(os.sep, "/")
    return any(rel == a or rel.startswith(a + "/") for a in anchored)


# --------------------------------------------------------------------------- git (no binary)

def _read_text(path: str):
    """Text file content, or None. Anything under .git may hold junk bytes: never raise."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _blob_sha_chunked(path: str, size: int):
    """Blob SHA-1 of a file too big to hold in memory, or None. No autocrlf folding:
    that needs the converted length up front, and huge files are not text anyway."""
    h = hashlib.sha1(b"blob %d\0" % size)
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _git_dirs(project_dir: str):
    """(gitdir, commondir) for a work tree, or None.

    A linked work tree (``git worktree add``) has a .git *file* pointing at
    .git/worktrees/<name>, which holds its own HEAD and index; its ``commondir``
    points back at the main .git for refs, packed-refs, reflogs and objects.
    """
    git_dir = os.path.join(project_dir, ".git")
    if os.path.isfile(git_dir):
        text = (_read_text(git_dir) or "").strip()
        if not text.startswith("gitdir:"):
            return None
        git_dir = text[len("gitdir:"):].strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(project_dir, git_dir)
        git_dir = os.path.normpath(git_dir)
    if not os.path.isdir(git_dir):
        return None
    common = (_read_text(os.path.join(git_dir, "commondir")) or "").strip()
    if not common:
        return git_dir, git_dir
    if not os.path.isabs(common):
        common = os.path.join(git_dir, common)
    return git_dir, os.path.normpath(common)


def _is_sha256(common_dir: str) -> bool:
    """sha256 repos name objects with sha256: our SHA-1 blob hashes can never match."""
    text = _read_text(os.path.join(common_dir, "config")) or ""
    return re.search(r"^\s*objectformat\s*=\s*sha256\s*$", text, re.M | re.I) is not None


def read_index(git_dir: str, common_dir: str | None = None):
    """Parse .git/index (v2/v3). Returns [(path, mtime_s, size, sha)] or None.

    None means "unknown, do not guess": index v4, a split index (entries live in
    .git/sharedindex.*), a sha256 repo, or a truncated file. An unmerged path is
    returned once with an empty sha -- a conflict is never clean.
    """
    if _is_sha256(common_dir or git_dir):
        return None
    try:
        with open(os.path.join(git_dir, "index"), "rb") as fh:
            b = fh.read()
    except OSError:
        return None
    if len(b) < 12 or b[:4] != b"DIRC":
        return None
    try:
        version, count = struct.unpack(">II", b[4:12])
        if version not in (2, 3):
            return None
        entries, unmerged, off = [], set(), 12
        for _ in range(count):
            if off + 62 > len(b):
                return None
            mtime_s = struct.unpack(">I", b[off + 8:off + 12])[0]
            mode = struct.unpack(">I", b[off + 24:off + 28])[0]
            size = struct.unpack(">I", b[off + 36:off + 40])[0]
            sha = b[off + 40:off + 60].hex()
            flags = struct.unpack(">H", b[off + 60:off + 62])[0]
            p = off + 62
            skip = bool(flags & 0x8000)                        # assume-valid
            if version == 3 and flags & 0x4000:                # extended flags
                if p + 2 > len(b):                             # truncated: unknown
                    return None
                if struct.unpack(">H", b[p:p + 2])[0] & 0x4000:  # skip-worktree
                    skip = True
                p += 2
            nul = b.find(b"\0", p)
            if nul == -1:
                return None
            name = b[p:nul].decode("utf-8", "replace")
            off += ((nul - off) + 8) & ~7                      # 1..8 NUL padding
            stage = (flags >> 12) & 0x3
            if stage:                                          # git status says "UU"
                if name not in unmerged:
                    unmerged.add(name)
                    entries.append((name, 0, 0, ""))
                continue
            if skip or (mode & 0xF000) != 0x8000:              # regular files only
                continue
            entries.append((name, mtime_s, size, sha))
        # Extensions follow the entries, each an ASCII signature + big-endian size.
        end = len(b) - 20                                      # trailing checksum
        while off + 8 <= end:
            sig = b[off:off + 4]
            if not sig.isalpha():
                break
            if sig == b"link":                                 # split index: not the whole truth
                return None
            off += 8 + struct.unpack(">I", b[off + 4:off + 8])[0]
    except struct.error:
        return None
    return entries


def modified_files(project_dir: str, git_dir: str, common_dir: str | None = None):
    """Tracked files whose content differs from the index. (files, partial, newest_mtime) or None."""
    entries = read_index(git_dir, common_dir)
    if entries is None:
        return None
    changed, newest, hashed = [], 0.0, 0
    for name, mtime_s, size, sha in entries:
        full = os.path.join(project_dir, *name.split("/"))
        try:
            st = os.stat(full)
        except OSError:
            changed.append(name)                           # deleted
            continue
        if not sha:                                        # unmerged path: always modified
            changed.append(name)
            newest = max(newest, st.st_mtime)
            continue
        if st.st_size == size and int(st.st_mtime) == mtime_s:
            continue                                       # git's own fast path
        hashed += 1
        if hashed > MAX_HASHES:
            return changed, True, newest
        if st.st_size > MAX_HASH_BYTES:
            # A rebuild often rewrites the same bytes, so "stat changed" alone is a
            # bad answer; hash it in chunks unless the file is big enough to hurt.
            if st.st_size <= HUGE_HASH_BYTES and _blob_sha_chunked(full, st.st_size) == sha:
                continue
            changed.append(name)
            newest = max(newest, st.st_mtime)
            continue
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if _blob_sha(data) == sha:
            continue
        if b"\r\n" in data and _blob_sha(data.replace(b"\r\n", b"\n")) == sha:
            continue                                       # autocrlf: same content
        changed.append(name)
        newest = max(newest, st.st_mtime)
    return changed, False, newest


_REFLOG_RE = re.compile(r"^([0-9a-f]{40,64}) ([0-9a-f]{40,64}) .*? (\d{9,11}) [+-]\d{4}\t(.*)$")
_COMMIT_MSG_RE = re.compile(r"^commit(?: \((?:initial|merge|amend)\))?: ")


def _reflog(git_dir: str, rel: str):
    """[(old_sha, new_sha, epoch, message)] for .git/logs/<rel>, or None if absent."""
    text = _read_text(os.path.join(git_dir, "logs", *rel.split("/")))
    if text is None:
        return None
    out = []
    for line in text.splitlines():
        m = _REFLOG_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2), int(m.group(3)), m.group(4)))
    return out


def _read_ref(git_dir: str, ref: str):
    text = _read_text(os.path.join(git_dir, *ref.split("/")))
    if text is not None:
        return text.strip()
    packed = _read_text(os.path.join(git_dir, "packed-refs"))   # after `git pack-refs`
    for line in (packed or "").splitlines():
        if line.endswith(" " + ref):
            return line.split(" ", 1)[0]
    return None


def _commit_parents(common_dir: str, sha: str):
    """Parent ids of a *loose* commit object, or None if it is packed/unreadable."""
    try:
        with open(os.path.join(common_dir, "objects", sha[:2], sha[2:]), "rb") as fh:
            raw = zlib.decompress(fh.read())
    except (OSError, zlib.error, IndexError):
        return None
    header, _, body = raw.partition(b"\0")
    if not header.startswith(b"commit "):
        return None
    return [line.split(b" ", 1)[1].decode("ascii", "replace")
            for line in body.split(b"\n\n", 1)[0].splitlines() if line.startswith(b"parent ")]


def _reach(common_dir: str, tip: str, stop: set):
    """(commits reachable from `tip` and not in `stop`, walk finished).

    Parents come from loose commit objects, which is exactly what local work is:
    anything fetched or cloned is packed, so the walk stops there and the caller
    falls back to the reflog rather than guessing.
    """
    out, queue, done = set(), [tip], True
    while queue:
        sha = queue.pop()
        if sha in stop or sha in out:
            continue
        parents = _commit_parents(common_dir, sha)
        if parents is None or len(out) >= MAX_WALK:
            done = False
            continue
        out.add(sha)
        queue.extend(parents)
    return out, done


def _unpushed(common_dir: str, branch: str, local: str, remote: str):
    """Commits on `branch` that origin/<branch> has never held -- the number
    `git rev-list --count @{u}..HEAD` gives. Only called with both refs known."""
    if local == remote:
        return 0
    # Both sides of every remote-tracking reflog entry, so a fetch that moved
    # origin/<branch> forward still marks the old tip as pushed. A fresh clone
    # writes no such reflog at all, which is why `remote` itself must be in here.
    log = _reflog(common_dir, "refs/remotes/origin/" + branch) or []
    seen = {sha for entry in log for sha in entry[:2] if sha.strip("0")} | {remote}
    origin_has, _ = _reach(common_dir, remote, set())      # best effort, packed = empty
    seen |= origin_has

    mine, done = _reach(common_dir, local, seen)
    if done:
        return len(mine)                                   # exact: real commit parents

    # Objects are packed (a gc'd repo). Fall back to the branch reflog: every entry
    # that moved the branch to a commit origin has not seen is local work -- a merge,
    # revert or cherry-pick as much as a plain commit -- de-duplicated because resets
    # revisit a sha. Known imprecision, always upwards: history the reflog remembers
    # but the branch no longer contains (an amend, a squashing rebase) is counted,
    # because a reflog entry's old sha is the previous *tip*, not the new commit's
    # parent. Only rewritten-then-packed work is affected; while it is still loose
    # the walk above answers exactly.
    # (Only reachable with the local tip unseen by origin, so the answer is >= 1.)
    branch_log = _reflog(common_dir, "refs/heads/" + branch)
    if branch_log is None:
        return 1                                           # no reflog either: at least one
    n, counted = 0, set()
    for old, sha, _, _ in reversed(branch_log):
        if sha in seen:
            break
        if sha not in counted:
            counted.add(sha)
            n += 1
        if old in seen:                                    # origin's tip is the parent
            break
    return max(n, 1)


def git_state(project_dir: str) -> GitState | None:
    dirs = _git_dirs(project_dir)
    if dirs is None:
        return None
    git_dir, common_dir = dirs                             # differ inside a linked worktree
    head = _read_text(os.path.join(git_dir, "HEAD"))
    if head is None:
        return None
    head = head.strip()
    branch = head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else None
    commits = [(ts, _COMMIT_MSG_RE.sub("", msg)) for _, _, ts, msg in (_reflog(git_dir, "HEAD") or [])
               if _COMMIT_MSG_RE.match(msg)]

    unpushed, has_remote = None, False
    if branch:
        remote = _read_ref(common_dir, "refs/remotes/origin/" + branch)
        local = _read_ref(common_dir, "refs/heads/" + branch)
        has_remote = bool(remote)
        if remote and local:
            unpushed = _unpushed(common_dir, branch, local, remote)

    mod = modified_files(project_dir, git_dir, common_dir)
    return GitState(
        branch=branch,
        has_remote=has_remote,
        unpushed=unpushed,
        last_commit=float(commits[-1][0]) if commits else 0.0,
        recent_commits=[msg for _, msg in reversed(commits[-3:])],
        modified=None if mod is None else mod[0],
        modified_partial=bool(mod and mod[1]),
        modified_newest=mod[2] if mod else 0.0,
    )


# --------------------------------------------------------------------------- walk + readme

def _walk(project_dir: str):
    rules = _load_gitignore(project_dir)
    files, newest, truncated = 0, 0.0, False
    recent: list[tuple[float, str]] = []
    stack = [project_dir]
    while stack:
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            try:
                if e.is_symlink():
                    continue
                rel = os.path.relpath(e.path, project_dir)
                if e.is_dir(follow_symlinks=False):
                    if e.name in PRUNE_DIRS or e.name.endswith(".egg-info") or _ignored(rules, rel, e.name):
                        continue
                    stack.append(e.path)
                    continue
                if not e.is_file(follow_symlinks=False) or _ignored(rules, rel, e.name):
                    continue
                files += 1
                if files > MAX_FILES:
                    truncated = True
                    stack.clear()
                    break
                m = e.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            newest = max(newest, m)
            recent.append((m, rel.replace(os.sep, "/")))
            if len(recent) > 64:
                recent.sort(reverse=True)
                del recent[16:]
    recent.sort(reverse=True)
    return files, newest, truncated, [r for _, r in recent[:5]]


def _plain(s: str) -> str:
    return re.sub(r"\*\*|__|`", "", s).strip()


def _todos(project_dir: str):
    # Match names from the real listing: Windows paths are case-insensitive, so
    # opening README.md and readme.md separately would count one file twice.
    try:
        present = {e.name.lower(): e.name for e in os.scandir(project_dir) if e.is_file()}
    except OSError:
        present = {}
    title, samples, count = "", [], 0
    for lower in TODO_FILES:
        if lower not in present:
            continue
        try:
            with open(os.path.join(project_dir, present[lower]), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if not title:
            m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
            title = _plain(m.group(1)) if m else ""
        items = TODO_RE.findall(text)
        count += len(items)
        samples.extend(_plain(i)[:140] for i in items)
    return title, count, samples[:3]


# --------------------------------------------------------------------------- public API

def _project(project_dir: str, now: float, git: GitState | None, extra: dict) -> Project:
    files, newest, truncated, recent = _walk(project_dir)
    title, open_todos, samples = _todos(project_dir)
    # A file dated in the future (bad clock, unzipped archive) is not work done later.
    last_work = min(max(newest, git.last_commit if git else 0.0), now)
    idle = int((now - last_work) // DAY) if last_work else 10**6
    return Project(
        name=os.path.basename(os.path.normpath(project_dir)), path=project_dir, last_work=last_work,
        idle_days=max(idle, 0), files=files, truncated=truncated, recent_files=recent,
        readme_title=title, open_todos=open_todos, todo_samples=samples, git=git, extra=extra,
    )


def scan_project(project_dir: str, now: float | None = None) -> Project:
    now = time.time() if now is None else now
    return _project(project_dir, now, git_state(project_dir), {})


def discover(roots: list[str], ignore: list[str] = (), track: list[str] = (), now: float | None = None):
    """Scan every direct sub-folder of each root. Returns (projects, skipped)."""
    projects, skipped = [], []
    ignore_set = {n.lower() for n in ignore}
    track_set = {n.lower() for n in track}
    for root in roots:
        try:
            kids = sorted(e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False))
        except OSError as exc:
            raise FileNotFoundError(f"Projects root not readable: {root} ({exc})") from exc
        names = set(kids)
        for name in kids:
            low = name.lower()
            if name.startswith(".") or (low in ignore_set and low not in track_set):
                skipped.append((name, "ignored"))
                continue
            copy = COPY_RE.match(name)
            if copy and copy.group(1) in names and low not in track_set:
                skipped.append((name, f"copy of {copy.group(1)}"))
                continue
            path = os.path.normpath(os.path.join(root, name))
            try:
                projects.append(scan_project(path, now=now))
            except Exception as exc:               # one unreadable project must not end the scan
                log.warning("scan failed for %s: %s: %s", path, type(exc).__name__, exc)
                try:                               # report it anyway, with git state unknown
                    projects.append(_project(path, time.time() if now is None else now, None,
                                             {"error": f"{type(exc).__name__}: {exc}"}))
                except Exception:
                    skipped.append((name, f"unreadable: {type(exc).__name__}"))
    return projects, skipped
