"""python -m adviser <command>

    serve              run the WhatsApp adviser: webhook + Cloudflare tunnel + Meta registration
    check              what is set up and what is missing (changes nothing)
    chat [--voice]     talk to the adviser in this terminal (no WhatsApp); --ask "..." for one question
    say "text"         speak a sentence into an OGG voice note file
    hear FILE          transcribe an audio file

Setup and the one-time Meta steps: docs/11-whatsapp-voice-adviser.md
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime

from reminder import remind

from . import brain, briefing, memory, speech, tunnel
from .server import AdviserServer
from .turn import Services, build_turn, handle
from .whatsapp import Client, Inbound

BASE_DIR = remind.BASE_DIR
DEFAULT_PORT = 8765
APP_SECRET_RE = re.compile(r"[0-9a-f]{32}")     # Meta's app secret: 32 hex characters, nothing else
log = logging.getLogger("adviser")


def setup_logging(base_dir: str, verbose: bool = False) -> None:
    os.makedirs(os.path.join(base_dir, ".state"), exist_ok=True)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(os.path.join(base_dir, ".state", "adviser.log"),
                                              maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    logging.getLogger("reminder").addHandler(fh)
    if sys.stderr is not None:                   # pythonw.exe has no console
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


def verify_token(base_dir: str, env: dict) -> str:
    """WA_VERIFY_TOKEN from .env, else a random one kept in .state (Meta only needs it to match)."""
    if env.get("WA_VERIFY_TOKEN"):
        return env["WA_VERIFY_TOKEN"]
    path = os.path.join(base_dir, ".state", "adviser", "verify_token.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            token = fh.read().strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(token)
    return token


def build_services(base_dir: str, env: dict, client=None, store=None) -> Services:
    try:
        pool = brain.ModelPool(brain.make_models(env))
    except Exception as exc:
        log.warning("No language model: %s", exc)
        pool = None
    return Services(base_dir=base_dir, env=env, client=client or Client.from_env(env),
                    store=store or memory.Store(base_dir), portfolio=brain.Portfolio(base_dir), pool=pool)


def owner(env: dict) -> str:
    return re.sub(r"\D", "", env.get("WA_TO") or env.get("WA_TARGET_NUMBER") or "")


# --------------------------------------------------------------------------- serve

def serve(args, env: dict, out=print) -> int:
    missing = [k for k in ("WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "WA_BUSINESS_ACCOUNT_ID", "WA_APP_SECRET")
               if not env.get(k)]
    if not owner(env):
        missing.append("WA_TARGET_NUMBER")
    if missing:
        out(f"Missing in .env: {', '.join(missing)}. See docs/11-whatsapp-voice-adviser.md, step 1.")
        return 2
    if not APP_SECRET_RE.fullmatch(env.get("WA_APP_SECRET") or ""):
        # Not fatal (only Meta decides what a valid secret is), but every webhook signature and the
        # registration call will fail, and the errors for that name the token, not the secret.
        log.warning("WA_APP_SECRET is %d characters; an app secret is 32 (digits and lower-case a-f). "
                    "Registration and every incoming message will be refused if it is wrong. Run "
                    "'python -m adviser check'.", len(env.get("WA_APP_SECRET") or ""))
    token = verify_token(BASE_DIR, env)
    services = build_services(BASE_DIR, env)
    turn = build_turn(services)

    def keep_scan_warm() -> None:
        """A scan takes several seconds; do it in the background so a message never waits for one."""
        while True:
            try:
                services.portfolio.refresh(force=True)
            except Exception as exc:
                log.warning("Project scan failed: %s", exc)
            time.sleep(brain.SNAPSHOT_TTL - 60)
    threading.Thread(target=keep_scan_warm, daemon=True, name="scan-warmer").start()
    to = owner(env)
    # One speaker, shared by the timer and by each answered message: its lock is what stops the
    # same check-in being spoken twice when the owner writes just as the timer comes round.
    speaker = briefing.Speaker(services, to)
    threading.Thread(target=speaker.run_forever, daemon=True, name="daily-briefing").start()

    def on_batch(batch) -> None:
        handle(turn, batch, to, apologise=services.client.send_text)
        speaker.tick()          # the owner just wrote, so a check-in that was waiting may go out now

    try:
        server = AdviserServer(env, services.store, on_batch, token, port=args.port).start()
    except OSError as exc:
        out(f"Port {args.port} is busy ({exc}). Is the adviser already running? Check .state/adviser.log.")
        return 3

    def remember(url: str) -> None:
        server.public_url = url
        with open(os.path.join(BASE_DIR, ".state", "adviser", "public_url.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"{url}/webhook\n")

    endpoint = None
    if args.public_url:
        url = args.public_url.rstrip("/")
        if url.endswith("/webhook"):
            url = url[: -len("/webhook")]
        if not args.no_register:
            try:
                tunnel.register(env, f"{url}/webhook", token)
                log.info("Webhook registered with Meta: %s/webhook", url)
            except tunnel.RegistrationError as exc:
                log.error("%s", exc)
        remember(url)
    elif not args.no_tunnel:
        exe = tunnel.find_cloudflared(env, BASE_DIR)
        if not exe:
            out("cloudflared was not found. Put cloudflared.exe in the tools folder or set ADVISER_CLOUDFLARED.")
            server.stop()
            return 2
        qt = tunnel.QuickTunnel(exe, server.port, os.path.join(BASE_DIR, ".state", "adviser", "cloudflared.log"))
        register = None if args.no_register else (lambda cb: tunnel.register(env, cb, token))
        endpoint = tunnel.PublicEndpoint(qt, register, on_url=remember)
        endpoint.start()
    log.info("Adviser running. Talk to it on WhatsApp from the number ending %s. Stop with Ctrl+C.", to[-3:])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping.")
    finally:
        if endpoint:
            endpoint.stop()
        server.stop()
    return 0


# --------------------------------------------------------------------------- local conversation

class ConsoleClient:
    """Stands in for WhatsApp: prints text replies and saves voice notes as files."""

    def __init__(self, folder: str, out=print):
        self.folder, self.out, self.n = folder, out, 0
        os.makedirs(folder, exist_ok=True)

    def mark_read(self, message_id, typing=True):
        pass

    def download(self, media_id):
        with open(media_id, "rb") as fh:                  # in chat, the "media id" is a local file path
            data = fh.read()
        return data, "audio/ogg" if media_id.lower().endswith((".ogg", ".opus")) else "audio/mpeg"

    def send_text(self, to, body):
        self.out(f"\nadviser> {body}\n")
        return "console-text"

    def send_voice(self, to, ogg):
        self.n += 1
        path = os.path.join(self.folder, f"reply-{datetime.now():%H%M%S}-{self.n}.ogg")
        with open(path, "wb") as fh:
            fh.write(ogg)
        self.out(f"\nadviser> [voice note, {len(ogg) // 1024} KB] {path}\n")
        return "console-voice"


def chat(args, env: dict, out=print, read=input) -> int:
    folder = os.path.join(BASE_DIR, ".state", "adviser", "console")
    store = memory.Store(BASE_DIR)
    store.dir = folder                                     # its own memory, apart from WhatsApp's
    if args.voice:
        env = {**env, "ADVISER_REPLY_MODE": "voice"}
    client = ConsoleClient(folder, out)
    services = build_services(BASE_DIR, env, client=client, store=store)
    turn = build_turn(services)
    n = 0

    def ask(text: str) -> None:
        nonlocal n
        n += 1
        if os.path.isfile(text) and text.lower().endswith((".ogg", ".opus", ".mp3")):
            msg = Inbound(id=f"console-{n}", sender="console", timestamp=int(time.time()), kind="voice",
                          media_id=text, mime="audio/ogg")
        else:
            msg = Inbound(id=f"console-{n}", sender="console", timestamp=int(time.time()), kind="text", text=text)
        t0 = time.time()
        result = handle(turn, [msg], "console")
        if result.get("trace"):
            out(f"  (looked at: {'; '.join(result['trace'])})")
        out(f"  ({time.time() - t0:.1f}s, {result.get('model') or 'no model'}, reply as {result.get('mode')})")

    if args.ask:
        ask(args.ask)
        return 0
    out("Talk to your second brain. Type a question, a path to a voice note (.ogg), /help, or 'quit'.")
    while True:
        try:
            text = read("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if text.lower() in ("quit", "exit", "q"):
            return 0
        if text:
            ask(text)


# --------------------------------------------------------------------------- brief

def brief(args, env: dict, out=print) -> int:
    """Say today's check-in out loud on WhatsApp, or just show what would be said."""
    services = build_services(BASE_DIR, env)
    data = memory.load_briefing(BASE_DIR)
    speaker = briefing.Speaker(services, owner(env))
    last = services.store.last_inbound()
    when = f"{datetime.fromtimestamp(last):%Y-%m-%d %H:%M}" if last else "never"
    open_now = speaker.window_open(time.time())      # the same rule the service itself uses
    if args.dry_run:
        out(briefing.script(data, datetime.now()) or
            "Nothing to say: the last reminder had no project that needs work.")
        out("")
        out(f"You last wrote to the adviser: {when}")
        out("WhatsApp window: open, this can be spoken now." if open_now else
            "WhatsApp window: closed. WhatsApp only allows a voice note within 24 hours of your own "
            "message, so this goes out the moment you write.")
        return 0
    what = speaker.tick()
    out({"spoken": "Spoken on WhatsApp.",
         "busy": "The running adviser is already dealing with it; nothing was sent twice.",
         "waiting": f"Waiting for you to write (you last wrote: {when}). WhatsApp allows a voice note "
                    "only within 24 hours of your own message; it goes out as soon as you do.",
         "nothing new": "Nothing new: today's check-in has already been spoken, or none has been sent.",
         "nothing to say": "The last reminder had no project that needs work.",
         "stale": "That check-in was too old to read out.",
         "text mode": "You asked for text only (/text), so it was not spoken.",
         "off": "Turned off by ADVISER_DAILY_VOICE in .env.",
         "failed": "It could not be spoken; see .state/adviser.log."}.get(what, what))
    return 0


# --------------------------------------------------------------------------- check

def check(env: dict, out=print) -> int:
    def row(ok, name, detail=""):
        out(f"  [{'x' if ok else ' '}] {name}" + (f"  - {detail}" if detail else ""))
        return ok

    out("WhatsApp adviser setup (nothing is changed or sent):")
    ok = True
    for key, why in (("WA_ACCESS_TOKEN", "the system-user token the reminder already uses"),
                     ("WA_PHONE_NUMBER_ID", "the business (test) number"),
                     ("WA_BUSINESS_ACCOUNT_ID", "the WhatsApp Business Account"),
                     ("GROQ_API_KEY", "thinking + speech-to-text")):
        ok &= row(bool(env.get(key)), key, "" if env.get(key) else f"missing: {why}")
    ok &= row(bool(owner(env)), "WA_TARGET_NUMBER", owner(env) and f"answers only …{owner(env)[-3:]}")
    secret = env.get("WA_APP_SECRET") or ""
    ok &= row(bool(APP_SECRET_RE.fullmatch(secret)), "WA_APP_SECRET",
              "set" if APP_SECRET_RE.fullmatch(secret) else
              "missing: Meta App Dashboard > App settings > Basic > App secret > Show; add WA_APP_SECRET=... to .env"
              if not secret else
              f"does not look like an app secret: {len(secret)} characters, and an app secret is exactly 32 "
              "(digits and lower-case a-f). Copy it again from App settings > Basic > App secret > Show, and "
              "paste only that value")
    row(True, "WA_APP_ID", env.get("WA_APP_ID") or "optional; read from the access token at start")
    row(True, "WA_VERIFY_TOKEN", "set in .env" if env.get("WA_VERIFY_TOKEN") else "optional; a random one is kept in .state")
    exe = tunnel.find_cloudflared(env, BASE_DIR)
    ok &= row(bool(exe), "cloudflared", exe or "missing: put cloudflared.exe in the tools folder")
    for mod in ("edge_tts", "soundfile", "langgraph", "langchain_groq"):
        try:
            __import__(mod)
            row(True, mod)
        except Exception as exc:
            ok &= row(False, mod, f"{exc}; run .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    out("Ready: run  .venv\\Scripts\\python.exe -m adviser serve" if ok else "Not ready yet: fix the unticked items.")
    return 0 if ok else 1


# --------------------------------------------------------------------------- main

def widen_console() -> None:
    """Let the console take anything the model writes. A Windows console is cp1252 by default, and
    the model's typography (narrow no-break spaces, dashes, emoji) raises UnicodeEncodeError there,
    which loses the whole reply. pythonw.exe has no console at all, hence the guards."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):            # a closed or unusual stream must not stop the run
                pass


def main(argv=None) -> int:
    widen_console()
    ap = argparse.ArgumentParser(prog="python -m adviser", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the WhatsApp adviser")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--no-tunnel", action="store_true", help="local only (for testing)")
    s.add_argument("--public-url", default="", help="use your own stable HTTPS address instead of a quick tunnel")
    s.add_argument("--no-register", action="store_true", help="do not change the webhook address at Meta")
    sub.add_parser("check", help="show what is set up")
    b = sub.add_parser("brief", help="speak today's check-in on WhatsApp, if WhatsApp allows it")
    b.add_argument("--dry-run", action="store_true", help="print what would be said and send nothing")
    c = sub.add_parser("chat", help="talk to the adviser in this terminal")
    c.add_argument("--voice", action="store_true", help="answer with voice-note files")
    c.add_argument("--ask", default="", help="ask one question and exit")
    sy = sub.add_parser("say", help="speak text into an OGG voice note")
    sy.add_argument("text")
    sy.add_argument("--out", default="")
    sy.add_argument("--voice-name", default="")
    h = sub.add_parser("hear", help="transcribe an audio file")
    h.add_argument("file")
    args = ap.parse_args(argv)

    env = remind.load_env(os.path.join(BASE_DIR, ".env"))
    setup_logging(BASE_DIR, args.verbose)
    if args.cmd == "serve":
        return serve(args, env)
    if args.cmd == "check":
        return check(env)
    if args.cmd == "brief":
        return brief(args, env)
    if args.cmd == "chat":
        return chat(args, env)
    if args.cmd == "say":
        notes = speech.voice_notes(args.text, voice=args.voice_name or env.get("ADVISER_VOICE") or speech.DEFAULT_VOICE,
                                   rate=env.get("ADVISER_VOICE_RATE") or "+0%")
        base = args.out or os.path.join(BASE_DIR, ".state", "adviser", "say.ogg")
        os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)
        for i, ogg in enumerate(notes):
            path = base if i == 0 else f"{os.path.splitext(base)[0]}-{i + 1}.ogg"
            with open(path, "wb") as fh:
                fh.write(ogg)
            print(f"{path}  ({len(ogg) // 1024} KB)")
        return 0
    if args.cmd == "hear":
        with open(args.file, "rb") as fh:
            data = fh.read()
        mime = "audio/ogg" if args.file.lower().endswith((".ogg", ".opus")) else "audio/mpeg"
        t = speech.transcribe(data, mime, env.get("GROQ_API_KEY", ""))
        print(f"[{t.language or '?'}, {t.seconds:.1f}s] {t.text}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
