"""What the adviser remembers between messages, all under .state/ (git-ignored).

    .state/adviser/conversation.json   the running conversation, reply mode, a pending change
    .state/adviser/seen.json           ids of messages already handled (Meta re-delivers)
    .state/briefing.json               what the last reminder said (written by the reminder)

The conversation starts over after a quiet spell (6 hours) or when a newer
reminder has gone out, so yesterday's topic does not leak into today's.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta

from reminder import remind

log = logging.getLogger("adviser")

KEEP_MESSAGES = 12              # 6 exchanges; each is resent to the model on every turn
MESSAGE_CHARS = 1500
IDLE_RESET_SECONDS = 6 * 3600
SEEN_KEEP_SECONDS = 8 * 86400   # Meta retries a failed delivery for up to 7 days
PENDING_SECONDS = 15 * 60
MODES = ("mirror", "voice", "text")


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{threading.get_ident()}.tmp"
    for attempt in range(5):                   # antivirus / indexer may hold the file for a moment
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def load_briefing(base_dir: str) -> dict:
    return _read_json(os.path.join(base_dir, ".state", "briefing.json"), {})


class Store:
    def __init__(self, base_dir: str, clock=time.time):
        self.base_dir = base_dir
        self.dir = os.path.join(base_dir, ".state", "adviser")
        self.clock = clock
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the customer service window
    #
    # WhatsApp allows a free-form message (a voice note among them) only within 24 hours of the
    # owner's last message, so the adviser has to know when that was. Kept here rather than in the
    # conversation, which is wiped whenever a new reminder arrives.

    def _window_path(self) -> str:
        return os.path.join(self.dir, "window.json")

    def note_inbound(self, when: float) -> None:
        """Remember when the owner wrote. Never raises: losing this only delays a spoken check-in.
        A time in the future is ignored: it can only come from a wrong clock or an odd payload, and
        once stored it would hold the window shut for ever."""
        try:
            when = float(when)
            if not 0 < when <= self.clock() + 300:
                log.warning("Ignored an impossible message time (%.0f).", when)
                return
            with self._lock:
                data = _read_json(self._window_path(), {})
                last = data.get("last_inbound")
                last = float(last) if isinstance(last, (int, float)) else 0.0
                if when > last:
                    _write_json(self._window_path(), {"last_inbound": when})
        except Exception as exc:
            log.warning("Could not record when the owner last wrote (%s).", exc)

    def last_inbound(self) -> float:
        value = _read_json(self._window_path(), {}).get("last_inbound")
        return float(value) if isinstance(value, (int, float)) else 0.0

    # ------------------------------------------------------------------ dedupe

    def first_time(self, message_id: str) -> bool:
        """True exactly once per message id, and remembers it (thread-safe)."""
        path = os.path.join(self.dir, "seen.json")
        now = self.clock()
        with self._lock:
            seen = _read_json(path, {})
            seen = {k: v for k, v in seen.items()
                    if isinstance(v, (int, float)) and now - v < SEEN_KEEP_SECONDS}
            if message_id in seen:
                return False
            seen[message_id] = now
            _write_json(path, seen)
            return True

    # ------------------------------------------------------------------ inbox (survives a crash)
    #
    # Meta gets its 200 as soon as a message is queued and will not send it again, so a message
    # that is queued or mid-turn when the process dies would be lost. Each one is written here
    # first and removed after its turn; leftovers are handled on the next start.

    def _inbox(self) -> str:
        return os.path.join(self.dir, "inbox")

    def _inbox_path(self, message_id: str) -> str:
        return os.path.join(self._inbox(), hashlib.sha1(message_id.encode("utf-8")).hexdigest() + ".json")

    def hold(self, message: dict) -> None:
        _write_json(self._inbox_path(message["id"]), {"message": message, "attempts": 0})

    def release(self, message_id: str) -> None:
        try:
            os.remove(self._inbox_path(message_id))
        except OSError:
            pass

    def leftovers(self, max_age: float, max_attempts: int = 2) -> list[dict]:
        """Messages a previous run accepted but never finished, oldest first. Each is tried at
        most `max_attempts` times, so a message that crashes the process cannot loop forever."""
        now, out = self.clock(), []
        try:
            names = sorted(n for n in os.listdir(self._inbox()) if n.endswith(".json"))
        except OSError:
            return out
        for name in names:
            path = os.path.join(self._inbox(), name)
            try:                                          # one damaged file must not stop the start
                held = _read_json(path, {})
                m = held.get("message") if isinstance(held.get("message"), dict) else None
                attempts = int(held.get("attempts") or 0)
                keep = bool(m) and str(m.get("id") or "") and now - float(m.get("timestamp") or 0) <= max_age \
                    and attempts < max_attempts
            except (TypeError, ValueError):
                m, keep, attempts = None, False, 0
            if not keep:
                log.warning("Dropping an unfinished message from an earlier run (%s).",
                            "too old or failed before" if m else "unreadable")
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            held["attempts"] = attempts + 1
            _write_json(path, held)
            out.append(m)
        return sorted(out, key=lambda m: float(m.get("timestamp") or 0))

    # ------------------------------------------------------------------ conversation

    def _path(self) -> str:
        return os.path.join(self.dir, "conversation.json")

    def conversation(self) -> dict:
        """The live conversation, already reset if it went stale."""
        now = self.clock()
        conv = _read_json(self._path(), {})
        conv.setdefault("messages", [])
        conv.setdefault("mode", "mirror")
        conv.setdefault("updated", 0)
        if conv["mode"] not in MODES:
            conv["mode"] = "mirror"
        briefing_at = _timestamp(load_briefing(self.base_dir).get("sent_at"))
        stale = conv["messages"] and (now - conv["updated"] > IDLE_RESET_SECONDS
                                      or (briefing_at and briefing_at > conv["updated"]))
        if stale:
            conv["messages"], conv["pending"] = [], None
        pending = conv.get("pending")
        if pending and now - pending.get("at", 0) > PENDING_SECONDS:
            conv["pending"] = None
        return conv

    def save(self, conv: dict) -> None:
        conv["messages"] = conv.get("messages", [])[-KEEP_MESSAGES:]
        conv["updated"] = self.clock()
        with self._lock:
            _write_json(self._path(), conv)

    def add(self, conv: dict, role: str, text: str, via: str = "text") -> None:
        text = (text or "").strip()
        if len(text) > MESSAGE_CHARS:
            text = text[: MESSAGE_CHARS - 1] + "…"
        conv.setdefault("messages", []).append({"role": role, "text": text, "via": via,
                                                "at": datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds")})

    def reset(self, conv: dict) -> None:
        conv["messages"], conv["pending"] = [], None


def timestamp(iso) -> float:
    """Seconds since the epoch for an ISO time, or 0.0 when it cannot be read."""
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return 0.0


_timestamp = timestamp


# --------------------------------------------------------------------------- reminder settings (confirmed changes only)

def apply_reminder_change(base_dir: str, project: str, action: str, days: int = 3, today: date | None = None) -> str:
    """Edit reminders.json for one project: done | snooze | reopen. Only ever called after the
    owner said yes. Keeps the "_help" comment keys, writes atomically, keeps the previous file
    in .state/reminders.json.bak, and puts it back if the result no longer loads."""
    today = today or date.today()
    path = os.path.join(base_dir, "reminders.json")
    with open(path, encoding="utf-8-sig") as fh:
        before = fh.read()
    raw = json.loads(before)
    done = [n for n in raw.get("done") or [] if isinstance(n, str)]
    snooze = raw.get("snooze") if isinstance(raw.get("snooze"), dict) else {}
    low = project.lower()
    done = [n for n in done if n.lower() != low]
    snooze = {n: d for n, d in snooze.items() if n.lower() != low}
    if action == "done":
        done.append(project)
        said = f"I've marked {project} as finished, so the daily reminder will stop mentioning it."
    elif action == "snooze":
        days = max(1, min(int(days), 60))
        until = today + timedelta(days=days)
        snooze[project] = until.isoformat()
        said = f"I've paused reminders about {project} until {until.strftime('%A %d %B')}."
    elif action == "reopen":
        said = f"{project} is back on the reminder list."
    else:
        raise ValueError(f"unknown action {action!r}")
    raw["done"], raw["snooze"] = done, snooze
    backup = os.path.join(base_dir, ".state", "reminders.json.bak")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    with open(backup, "w", encoding="utf-8") as fh:
        fh.write(before)
    _write_json(path, raw)
    try:
        remind.load_config(base_dir)
    except Exception:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(before)
        raise
    log.info("reminders.json: %s %s", action, project)
    return said
