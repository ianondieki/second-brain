"""Read-only tools the investigator agent may use on ONE project folder.

Every tool is bound to a single project directory and refuses anything outside
it (path traversal, symlinks out), secret files (.env, keys) and binaries, and
masks secret-looking values in text it returns. The agent can look, never touch.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import time

from langchain_core.tools import StructuredTool

from .scan import DAY, PRUNE_DIRS, RUNTIME_NAME, Project

log = logging.getLogger("reminder")

SECRET_FILE = re.compile(r"(^\.env(\..+)?$|\.(pem|key|p12|pfx|jks|kdbx)$|^id_(rsa|ed25519|ecdsa)(\.pub)?$"
                         r"|credentials\.json$|token\.json$"
                         r"|(^|[._-])env(rc)?([._-]|$)"          # prod.env, .env-local, .env_backup, .envrc
                         r"|^\.(pgpass|netrc|npmrc|pypirc|git-credentials)$)", re.I)
# key = value / key: value, including JSON-style "key": "value"; the value runs to end of
# line. The keyword must be a whole segment (API_KEY, db.password, access-token, DB_PASS,
# STRIPE_SK), a camelCase part (apiKey), or the end of a fused name (PGPASSWORD), so
# "monkey = 1", "keyboard: x" and "max_tokens = 5" are left alone.
_KW = r"(?:key|secret|password|passwd|pwd|pass|sk|token|authorization|apikey|credentials?)"
SECRET_LINE = re.compile(
    r"(?<![\w.-])([\"']?)("
    r"(?i:(?:[\w.-]*[_.-])?" + _KW + r"(?:[_.-][\w.-]*)?)"
    r"|[\w.-]*[a-z](?:Key|Secret|Password|Passwd|Pwd|Token|Authorization|ApiKey|Credentials?)[\w.-]*"
    r"|(?i:[\w.-]*(?:password|passwd|secret|token|apikey))"
    r")(\1\s*[:=]\s*)(.+)$", re.M)
# Values shaped like real keys, wherever they appear (Groq("gsk_..."), a pasted Meta token).
SECRET_TOKEN = re.compile(r"\b(?:gsk_[A-Za-z0-9]{20,}|sk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}"
                          r"|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{30,}"
                          r"|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}"
                          r"|EAA[A-Za-z0-9]{40,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}"
                          r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"      # JWT
                          r"|\d{8,10}:[A-Za-z0-9_-]{35})")                                          # Telegram bot
# define('DB_PASSWORD', 'x'), os.environ.setdefault("API_KEY", "x")
SECRET_CALL = re.compile(r"""(["'])([\w.-]*(?i:password|passwd|secret|token|api_?key)[\w.-]*)\1(\s*,\s*)(["'])"""
                         r"""[^"'\n]+\4""")
# user:password@ inside URLs such as postgres://user:pass@host/db
SECRET_URL = re.compile(r"(://[^/\s:@]+:)[^@\s]+@")
# PEM bodies wherever they appear (also a BEGIN line whose END fell outside the chunk)
SECRET_PEM = re.compile(r"-----BEGIN [^-\n]+-----[\s\S]*?(?:-----END [^-\n]+-----|\Z)")
MAX_TOOL_CHARS = 4_000          # every tool result is resent on each later step: keep them small
MAX_LINES = 120
MAX_FILE_BYTES = 2_000_000
TEXT_EXT = re.compile(r"\.(md|txt|rst|py|js|mjs|ts|tsx|jsx|json|ya?ml|toml|ini|cfg|html?|css|sql|sh|ps1|bat"
                      r"|csv|xml|java|kt|go|rs|c|h|cpp|hpp|cs|rb|php|ipynb|env\.example|gitignore|dockerfile"
                      r"|makefile)$", re.I)


class ToolRefused(ValueError):
    pass


def redact(text: str) -> str:
    text = SECRET_PEM.sub("[redacted key block]", text)
    text = SECRET_URL.sub(r"\1[redacted]@", text)
    text = SECRET_TOKEN.sub("[redacted]", text)
    text = SECRET_CALL.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}{m.group(4)}[redacted]{m.group(4)}",
                           text)
    return SECRET_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[redacted]", text)


def _clip(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… [truncated at {limit} characters]"


def make_tools(project: Project) -> list[StructuredTool]:
    root = os.path.realpath(project.path)

    def inside(full: str) -> bool:
        real = os.path.realpath(full)               # resolves symlinks AND Windows junctions
        return real == root or real.startswith(root + os.sep)

    def resolve(rel: str) -> str:
        rel = (rel or "").strip().strip("/\\")
        full = os.path.realpath(os.path.join(root, rel)) if rel else root
        if not inside(full):
            raise ToolRefused(f"'{rel}' is outside the project folder; only paths inside it can be read.")
        return full

    def refuse_hardlink(full: str) -> None:
        # A hard link is indistinguishable from a normal file by path, but can point at
        # content outside the project. Real project files almost never have extra links.
        try:
            if os.stat(full).st_nlink > 1:
                raise ToolRefused("that file has other hard links and might not belong to this project.")
        except OSError:
            pass

    def is_text_file(full: str) -> bool:
        try:
            with open(full, "rb") as fh:
                head = fh.read(8192)
        except OSError:
            return False
        return b"\0" not in head

    def list_files(subdir: str = "") -> str:
        """List the files and folders directly inside a sub-folder of the project (use "" for the
        project root). Each line shows: name, size and how many days since it last changed.
        Folders end with '/'. Dependency and cache folders are hidden."""
        full = resolve(subdir)
        if not os.path.isdir(full):
            raise ToolRefused(f"'{subdir}' is not a folder in this project.")
        now = time.time()
        rows = []
        for e in sorted(os.scandir(full), key=lambda x: (not x.is_dir(), x.name.lower())):
            if e.is_dir(follow_symlinks=False):
                if e.name in PRUNE_DIRS or e.name.endswith(".egg-info"):
                    continue
                rows.append(f"{e.name}/")
            elif e.is_file(follow_symlinks=False):
                if RUNTIME_NAME.match(e.name) or SECRET_FILE.search(e.name):
                    continue
                st = e.stat()
                rows.append(f"{e.name}  {st.st_size:,} bytes  changed {int((now - st.st_mtime) // DAY)}d ago")
        return _clip("\n".join(rows) or "(empty folder)")

    def read_file(path: str, start_line: int = 1, max_lines: int = 80) -> str:
        """Read a text file inside the project. `path` is relative to the project root, e.g.
        "README.md" or "src/app.py". Returns numbered lines from `start_line`, at most `max_lines`
        (up to 120). Secret files (.env, keys) and binary files are refused."""
        full = resolve(path)
        name = os.path.basename(full)
        if not os.path.isfile(full):
            raise ToolRefused(f"'{path}' is not a file in this project. Use list_files to see what exists.")
        if RUNTIME_NAME.match(name) or SECRET_FILE.search(name):
            raise ToolRefused(f"'{path}' looks like a secrets file and is not readable by this tool.")
        if os.path.getsize(full) > MAX_FILE_BYTES or not is_text_file(full):
            raise ToolRefused(f"'{path}' is binary or too large to read here.")
        refuse_hardlink(full)
        with open(full, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        start = max(int(start_line), 1)
        count = min(max(int(max_lines), 1), MAX_LINES)
        chunk = lines[start - 1:start - 1 + count]
        body = "\n".join(f"{start + i:>5}: {l}" for i, l in enumerate(chunk))
        tail = f"\n… {len(lines) - (start - 1 + len(chunk))} more lines" if start - 1 + len(chunk) < len(lines) else ""
        return _clip(redact(body) + tail)

    def search_files(pattern: str, max_hits: int = 20) -> str:
        """Case-insensitive regular-expression search across the project's text files (e.g.
        "TODO|FIXME", "def main"). Returns up to `max_hits` matching lines as path:line: text."""
        try:
            rx = re.compile(pattern, re.I)
        except re.error as exc:
            raise ToolRefused(f"Bad regular expression: {exc}")
        hits, limit = [], min(max(int(max_hits), 1), 50)
        stack = [root]
        while stack and len(hits) < limit:
            d = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda x: x.name.lower())
            except OSError:
                continue
            for e in entries:
                if len(hits) >= limit:
                    break
                if e.is_dir(follow_symlinks=False):
                    # is_dir(follow_symlinks=False) is True for a Windows junction, so check
                    # where it really leads before walking into it.
                    if e.name not in PRUNE_DIRS and not e.name.endswith(".egg-info") and inside(e.path):
                        stack.append(e.path)
                    continue
                if not e.is_file(follow_symlinks=False) or RUNTIME_NAME.match(e.name) or SECRET_FILE.search(e.name):
                    continue
                if not TEXT_EXT.search(e.name) and "." in e.name:
                    continue
                try:
                    st = os.stat(e.path)            # not e.stat(): on Windows that leaves st_nlink at 0
                    if st.st_size > MAX_FILE_BYTES or st.st_nlink > 1 or not inside(e.path) or not is_text_file(e.path):
                        continue
                    with open(e.path, encoding="utf-8", errors="replace") as fh:
                        for n, line in enumerate(fh, 1):
                            if rx.search(line):
                                rel = os.path.relpath(e.path, root).replace(os.sep, "/")
                                hits.append(f"{rel}:{n}: {redact(line.rstrip())[:240]}")
                                if len(hits) >= limit:
                                    break
                except OSError:
                    continue
        return _clip("\n".join(hits) or "No matches.")

    def git_summary() -> str:
        """Git facts read from the project's .git folder: branch, recent commits, files changed
        but not committed, and commits not pushed. Says so if the project is not in git."""
        g = project.git
        if g is None:
            return "This folder is not a git repository."
        lines = [f"branch: {g.branch or '(detached)'}",
                 f"last commit: {int((time.time() - g.last_commit) // DAY)} days ago" if g.last_commit else "no commits",
                 "recent commits: " + ("; ".join(g.recent_commits) if g.recent_commits else "none"),
                 "uncommitted changes: " + (", ".join(g.modified[:20]) if g.modified else
                                            ("unknown" if g.modified is None else "none")),
                 f"unpushed commits: {'unknown' if g.unpushed is None else g.unpushed}"
                 + ("" if g.has_remote else " (no remote configured)")]
        return "\n".join(lines)

    def guarded(fn):
        @functools.wraps(fn)                 # keeps the signature LangChain turns into the args schema
        def wrapper(*a, **kw):
            t0 = time.time()
            try:
                return fn(*a, **kw)
            except ToolRefused as exc:
                return f"Refused: {exc}"
            except OSError as exc:
                return f"Could not read: {type(exc).__name__}: {exc}"
            finally:
                log.debug("tool %s%s: %.2fs", fn.__name__, kw or a, time.time() - t0)
        return wrapper

    return [StructuredTool.from_function(guarded(fn), name=fn.__name__, description=fn.__doc__)
            for fn in (list_files, read_file, search_files, git_summary)]
