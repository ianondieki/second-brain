"""The daily reminder, spoken.

WhatsApp only lets a business open a conversation with an approved template, and a template
cannot carry audio, so a voice note can never be pushed out of the blue. Free-form messages,
voice notes among them, are allowed only inside the customer service window, which opens when
the owner writes and lasts 24 hours. So the daily check-in is spoken as soon as it is allowed:
straight away when the window is open, otherwise on the owner's next message, and never once
the reminder it describes has gone stale.

Every sentence comes from what the reminder actually sent (.state/briefing.json), so the voice
cannot invent a project or a next step. Nothing here can make the reminder itself fail: it runs
in the adviser, after the fact.

Saying it twice is the failure that matters, because the owner cannot undo hearing it. Three
things prevent it: a claim written *before* the first note is sent (so an interrupted send is
never retried blindly), a lock file (so `adviser brief` in another window cannot race the
service), and a hash of the words (so the reminder's own half-hourly retry, which rewrites the
file with a new timestamp and the same content, is recognised as the same check-in).
"""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime

from . import memory, speech

log = logging.getLogger("adviser")

WINDOW_SECONDS = 23.5 * 3600     # Meta allows 24 h from the owner's last message; stay off the edge
FRESH_SECONDS = 14 * 3600        # an older check-in is not worth speaking
TICK_SECONDS = 60
RETRY_AFTER = 15 * 60            # wait this long before spending another attempt
LOCK_STALE_SECONDS = 10 * 60
MAX_SPOKEN = 2                   # projects described in full; the rest are counted
MAX_ATTEMPTS = 4                 # attempts per check-in, spread by RETRY_AFTER
FIELD_CHARS = 240                # one spoken field; the reminder already clips, this is the backstop
OPENERS = ("First,", "Then,", "After that,")
ACTIONABLE = ("unfinished", "unclear")
NUMBER = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def _spoken_number(n: int) -> str:
    return NUMBER.get(n, str(n))


def greeting(now: datetime) -> str:
    return "Good morning." if now.hour < 12 else "Good afternoon." if now.hour < 18 else "Good evening."


def _sentence(text: str, limit: int = FIELD_CHARS) -> str:
    """One spoken sentence: no markdown, no double spaces, bounded, ends in a full stop."""
    clean = " ".join(str(text or "").replace("*", "").replace("`", "").split()).strip()
    if len(clean) > limit:
        clean = clean[:limit].rsplit(" ", 1)[0]
    if clean and clean[-1] not in ".!?:":
        clean += "."
    return clean


def actionable_projects(briefing: dict) -> list[dict]:
    return [p for p in (briefing.get("projects") or [])
            if isinstance(p, dict) and p.get("name") and str(p.get("status") or "unclear") in ACTIONABLE]


def script(briefing: dict, now: datetime) -> str:
    """The spoken check-in. Empty when there is nothing worth saying out loud."""
    projects = actionable_projects(briefing)
    if not projects:
        return ""
    n = len(projects)
    lines = [f"{greeting(now)} Here is your project check-in."]
    if n == 1:
        lines.append(f"One project needs you today: {_sentence(projects[0]['name'], 80)[:-1]}.")
    else:
        lines.append(f"{_spoken_number(n).capitalize()} projects need you today.")
    for i, p in enumerate(projects[:MAX_SPOKEN]):
        if n > 1:                                   # with one project the name is already in the line above
            lines.append(f"{OPENERS[i]} {_sentence(p['name'], 80)}")
        if p.get("why"):
            why = _sentence(p["why"])
            lines.append(why[:1].upper() + why[1:])
        if p.get("left_off"):
            lines.append("Where you left off: " + _sentence(p["left_off"]))
        if p.get("next_step"):
            lines.append("Your next step, about fifteen minutes: " + _sentence(p["next_step"]))
    if n > MAX_SPOKEN:
        rest = n - MAX_SPOKEN
        lines.append(f"There {'is' if rest == 1 else 'are'} {_spoken_number(rest)} more in today's email.")
    lines.append("The full list is in that email. Reply here any time and I will go deeper on any of them.")
    return " ".join(x for x in lines if x)


class _OtherProcessIsSpeaking(Exception):
    pass


class Speaker:
    """Speaks each new check-in once, as soon as WhatsApp allows it."""

    def __init__(self, svc, to: str, *, window_seconds: float = WINDOW_SECONDS,
                 fresh_seconds: float = FRESH_SECONDS, max_attempts: int = MAX_ATTEMPTS,
                 retry_after: float = RETRY_AFTER):
        self.svc, self.to = svc, to
        self.window_seconds, self.fresh_seconds = window_seconds, fresh_seconds
        self.max_attempts, self.retry_after = max_attempts, retry_after
        self.dir = os.path.join(svc.base_dir, ".state", "adviser")
        self.path = os.path.join(self.dir, "spoken.json")
        self.lock_path = self.path + ".lock"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> bool:
        """True when the record is safely on disk. A record that cannot be written means the
        check-in must not be sent, because nothing would stop it being sent again a minute later."""
        tmp = f"{self.path}.{os.getpid()}.{threading.get_ident()}.tmp"
        for attempt in range(5):                    # antivirus and the indexer hold files briefly
            try:
                os.makedirs(self.dir, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, sort_keys=True)
                os.replace(tmp, self.path)
                return True
            except OSError as exc:
                if attempt == 4:
                    log.warning("Could not record the spoken check-in (%s); it will not be sent.", exc)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return False
                time.sleep(0.2 * (attempt + 1))
        return False

    def _done(self, sent_at: str, how: str, text: str = "") -> None:
        record = {"spoken_for": sent_at, "how": how,
                  "at": datetime.fromtimestamp(self.svc.clock()).isoformat(timespec="seconds")}
        if text:
            record["spoken_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
            record["spoken_day"] = datetime.fromtimestamp(self.svc.clock()).date().isoformat()
        self._write(record)

    # ------------------------------------------------------------------ one speaker at a time, across processes

    def _take_lock(self) -> int:
        try:
            if time.time() - os.path.getmtime(self.lock_path) > LOCK_STALE_SECONDS:
                os.remove(self.lock_path)           # a process that died mid-send
        except OSError:
            pass
        try:
            os.makedirs(self.dir, exist_ok=True)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise _OtherProcessIsSpeaking()
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise _OtherProcessIsSpeaking()
            raise
        os.write(fd, str(os.getpid()).encode())
        return fd

    def _drop_lock(self, fd: int) -> None:
        try:
            os.close(fd)
        finally:
            try:
                os.remove(self.lock_path)
            except OSError:
                pass

    # ------------------------------------------------------------------ decisions

    def window_open(self, now: float) -> bool:
        """WhatsApp allows a free-form message only within 24 hours of the owner's last one."""
        last = self.svc.store.last_inbound()
        return bool(last) and 0 <= now - last <= self.window_seconds

    def reply_mode(self) -> str:
        try:
            return str(self.svc.store.conversation().get("mode") or "mirror")
        except Exception:                           # a damaged conversation file must not stop the check-in
            return "mirror"

    def tick(self) -> str:
        """Speak today's check-in if it is due and allowed. Returns what happened, for the log and
        the tests: spoken | waiting | busy | nothing new | stale | nothing to say | text mode |
        off | failed."""
        if not self._lock.acquire(blocking=False):
            return "busy"                           # the timer thread is already doing it
        try:
            fd = self._take_lock()
        except _OtherProcessIsSpeaking:
            self._lock.release()                    # or this speaker would stay "busy" for ever
            return "busy"
        except Exception:
            log.exception("The spoken check-in could not take its lock")
            self._lock.release()
            return "failed"
        try:
            return self._tick()
        except Exception:
            log.exception("The spoken check-in failed")
            return "failed"
        finally:
            self._drop_lock(fd)
            self._lock.release()

    def _tick(self) -> str:
        if str(self.svc.env.get("ADVISER_DAILY_VOICE") or "on").lower() in ("off", "0", "no", "false"):
            return "off"
        briefing = memory.load_briefing(self.svc.base_dir)
        sent_at = str(briefing.get("sent_at") or "")
        if not sent_at:
            return "nothing new"
        state = self._read()
        if state.get("spoken_for") == sent_at:
            return "nothing new"
        if state.get("claimed") == sent_at and state.get("failed_for") != sent_at:
            # The first note was already on its way when this process stopped. Saying it again is
            # worse than staying quiet: the email has the same content either way.
            self._done(sent_at, "assumed spoken; the last attempt was interrupted")
            log.info("An earlier attempt at today's check-in was interrupted; not repeating it.")
            return "nothing new"
        now = self.svc.clock()
        age = now - memory.timestamp(sent_at)
        if age > self.fresh_seconds:                # the adviser was off; do not read out yesterday's news
            self._done(sent_at, "stale")
            log.info("Today's check-in was too old to speak (%.1f h).", age / 3600)
            return "stale"
        if not actionable_projects(briefing):
            self._done(sent_at, "nothing to say")
            return "nothing to say"
        if self.reply_mode() == "text":             # the owner asked for text only; the email already says it
            self._done(sent_at, "text mode")
            return "text mode"
        if not self.window_open(now):
            return "waiting"                        # not recorded: it goes out when the owner next writes
        text = script(briefing, datetime.fromtimestamp(now))
        parts = speech.plan_voice(text)
        if not text or not parts:
            self._done(sent_at, "nothing to say")
            return "nothing to say"
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()
        today = datetime.fromtimestamp(now).date().isoformat()
        if state.get("spoken_hash") == key and state.get("spoken_day") == today:
            # The reminder retried a channel and rewrote the file with a new time and the same
            # words (it runs every half hour until both channels are done).
            self._done(sent_at, "same as the one already spoken today", text)
            return "nothing new"
        tries = int(state.get("tries") or 0) if state.get("failed_for") == sent_at else 0
        if tries >= self.max_attempts:
            self._done(sent_at, f"given up after {tries}")
            return "failed"
        if tries and now - float(state.get("tried_at") or 0) < self.retry_after:
            return "waiting"                        # space the attempts out; a blip should not burn the day
        if not self._write({**state, "claimed": sent_at, "claimed_at": now}):
            return "failed"                         # never send what cannot be recorded
        return self._speak(sent_at, text, parts, tries, key, today)

    # ------------------------------------------------------------------ speaking

    def _speak(self, sent_at: str, text: str, parts: list, tries: int, key: str, today: str) -> str:
        voice = self.svc.env.get("ADVISER_VOICE") or speech.DEFAULT_VOICE
        rate = self.svc.env.get("ADVISER_VOICE_RATE") or "+0%"
        sent, spoken_to = [], 0
        try:
            for i, part in enumerate(parts):
                for ogg in self.svc.render_note(part, voice=voice, rate=rate):
                    sent.append(self.svc.client.send_voice(self.to, ogg))
                spoken_to = i + 1
        except BaseException as exc:                # incl. CancelledError from edge-tts's event loop
            log.warning("Could not speak the check-in (%s: %s); attempt %d of %d.",
                        type(exc).__name__, exc, tries + 1, self.max_attempts)
            if sent:                                # part of it was heard: send the rest as text, once
                rest = " ".join(parts[spoken_to:]).strip()
                if rest:
                    try:
                        self.svc.client.send_text(self.to, rest)
                    except Exception as also:
                        log.warning("The rest of the check-in could not be sent as text either (%s).", also)
                self._done(sent_at, f"partly spoken in {len(sent)} note(s), the rest as text", text)
                return "failed"
            self._write({"failed_for": sent_at, "tries": tries + 1, "tried_at": self.svc.clock()})
            return "failed"
        self._done(sent_at, f"spoken in {len(sent)} note(s)", text)
        self._remember(text)
        log.info("Spoke today's check-in in %d voice note(s).", len(sent))
        return "spoken"

    def _remember(self, text: str) -> None:
        """Put the check-in in the conversation, so a reply like "tell me more about the second one"
        has something to point at, and so the adviser does not repeat itself. The role must be one
        the model actually reads (brain.build_messages keeps "user" and "assistant" only)."""
        try:
            conv = self.svc.store.conversation()
            self.svc.store.add(conv, "assistant", text, via="voice")
            self.svc.store.save(conv)
        except Exception as exc:
            log.warning("Could not add the spoken check-in to the conversation (%s).", exc)

    # ------------------------------------------------------------------ background

    def run_forever(self, stop: threading.Event | None = None, tick_seconds: float = TICK_SECONDS) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            what = self.tick()
            if what not in ("nothing new", "waiting", "off", "busy"):
                log.debug("Spoken check-in: %s", what)
            stop.wait(tick_seconds)
