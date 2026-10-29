"""One turn of the conversation, as a LangGraph workflow.

    START ─▶ acknowledge ─▶ hear ─┬─(nothing to answer)──────────────────────────▶ END
                                  └─▶ route ─┬─(command / confirmation)─┬─▶ speak ─▶ deliver ─▶ END
                                             └─▶ think (adviser agent) ─┘

acknowledge  blue ticks + "typing…" straight away, so the owner knows it was heard
hear         voice notes are downloaded and transcribed; text is taken as it is
route        /commands and "yes"/"no" to a pending reminder change, decided in code
think        the adviser agent (brain.py) answers
speak        in voice mode, the answer becomes voice notes, each sent the moment it is ready
deliver      the text: the whole answer, or the [[text]] part after voice notes; memory is saved

Every node turns its own failure into a plainer reply (a text instead of a voice
note, an apology instead of silence), so a turn always ends with an answer.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from . import brain, memory, speech
from .whatsapp import Client, Inbound, for_whatsapp

log = logging.getLogger("adviser")

VOICE_ASK = re.compile(r"\b(voice ?note|voice (reply|message)|send (me )?(a )?voice|say it|speak|audio)\b", re.I)
STT_WORDS = "commit, push, README, LangGraph, WhatsApp, Groq, API, repo, TODO"

# ---- the yes/no gate for reminder changes (decided here, never by the model)
#
# Only a message that is nothing but a yes changes anything. Anything mixed ("Yes, not yet",
# "Okay, no thanks", "Ndio, lakini subiri") or short and unclear gets the question again; a
# longer message about something else lets the proposal lapse. Two review rounds found
# retractions hiding after a yes, so there is deliberately no "yes, and ..." shortcut.
_YES = (r"yes|yeah|yea|yep|yup|ya|sure|sure thing|ok|okay|correct|confirm(?:ed)?|do it|go ahead|go for it|"
        r"please do|absolutely|of course|definitely|ndio|ndiyo|sawa|\U0001F44D|✅")
_NO = (r"no|nope|nah|cancel|don'?t|do not|stop|wait|hold on|not yet|not now|later|never|nevermind|never mind|"
       r"scratch that|leave it|keep it|hapana|subiri|si sasa|usifanye|\U0001F44E|❌|\U0001F6D1")
_POLITE = r"please|thanks|thank you|go ahead|do it|sure|yes|ok|okay|for now"
YES_ONLY = re.compile(rf"^(?:{_YES})(?:[\s,!.]+(?:{_POLITE}))*[\s!.]*$", re.I)
NO_ONLY = re.compile(rf"^(?:{_NO})(?:[\s,!.]+(?:{_POLITE}|{_NO}|it|that))*[\s!.]*$", re.I)
STARTS_YES_OR_NO = re.compile(rf"^(?:{_YES}|{_NO})(?![\w'])", re.I)


def yes_or_no(text: str) -> str:
    """"yes" | "no" | "unclear" | "other"."""
    t = re.sub(r"[‘’ʼ´`]", "'", text or "")       # iPhone apostrophes: don’t -> don't
    t = re.sub(r"\s+", " ", t.strip().strip("\"'*_~")).strip()
    t = re.sub(r"️", "", t)                                      # emoji variation selector
    hesitant = t.endswith(("...", "…"))                         # "Okay..." is not a yes
    if YES_ONLY.match(t) and not hesitant:
        return "yes"
    if NO_ONLY.match(t):
        return "no"
    if len(t.split()) <= 8 or STARTS_YES_OR_NO.match(t):
        return "unclear"
    return "other"


# The model sometimes claims a reminder change it cannot make ("Portfolio is marked as done and off
# your list"). Such sentences are dropped from every reply, whoever the subject is; only plain code
# ever says a change was made.
CHANGE_WORDS = re.compile(r"\b(marked|paused|snoozed|removed|reopened|stopped remind\w*|turned off|taken off|"
                          r"off your (?:reminder )?list|put (?:it |\w+ )?back on)\b", re.I)
REMINDER_TOPIC = re.compile(r"remind|\blist\b|\b(?:done|finished|complete|completed)\b", re.I)


def drop_change_claims(reply: str) -> tuple[str, bool]:
    kept, dropped = [], False
    for s in re.split(r"(?<=[.!?)])\s+", reply.strip()):
        if s and CHANGE_WORDS.search(s) and REMINDER_TOPIC.search(s):
            dropped = True
            continue
        kept.append(s)
    return " ".join(k for k in kept if k), dropped


# A proposal is only a proposal: models still say "I've marked it as finished", so the question
# is asked in fixed words, and sentences about the reminder that claim a change or ask their own
# confirmation are dropped.
CONFIRM = {"done": "Shall I stop reminding you about {project}?",
           "snooze": "Shall I pause reminders about {project} for {days} days?",
           "reopen": "Shall I put {project} back on your reminder list?"}
_CLAIMER = r"\b(i'?ve|i have|i just|it'?s now|it is now|now)\b[^.?!]{0,60}?"
CLAIMS_CHANGE = re.compile(_CLAIMER + r"\b(marked|paused|snoozed|stopped|removed|reopened)\b", re.I)
CLAIMS_EDIT = re.compile(_CLAIMER + r"\b(updated|changed|added|set)\b", re.I)      # only about the reminder
ASKS_CONFIRM = re.compile(r"\bconfirm|\breply\b.{0,20}\byes\b|\byes\b.{0,20}\bno\b", re.I)


def confirm_proposal(reply: str, proposal: dict) -> str:
    about = re.compile(rf"remind|\blist\b|{re.escape(proposal['project'])}", re.I)
    kept = []
    for s in re.split(r"(?<=[.!?)])\s+", drop_change_claims(reply)[0]):
        if not s or s.rstrip(" *_)").endswith("?"):           # one question only: ours
            continue
        if CLAIMS_CHANGE.search(s) or ((CLAIMS_EDIT.search(s) or ASKS_CONFIRM.search(s)) and about.search(s)):
            continue
        kept.append(s)
    return " ".join(kept + [question_for(proposal)])


def question_for(proposal: dict) -> str:
    return CONFIRM[proposal["action"]].format(**proposal) + " Say yes or no."


RETYPE_AFTER = 15               # seconds; WhatsApp drops the typing indicator after 25
PARALLEL_NOTES = 3              # voice notes synthesized at the same time

HELP = """*Talk to your second brain* \U0001F9E0
Send a text or a voice note about any project. For example:
- "Where did I leave off on personal-assistant?"
- "Explain soc-agents to me simply."
- "What should I work on today?"
- "I finished portfolio." (it will ask before changing your reminders)

*Commands*
- /voice : always answer with voice notes
- /text : always answer in text
- /auto : answer the way you asked (voice for a voice note)
- /projects : your projects and their state
- /reset : start a fresh conversation
- /help : this message"""

BUSY = ("Sorry, my thinking engine is overloaded right now, so I could not work that out. "
        "Give me a minute and ask again.")
DEAF = ("Sorry, I could not make out that voice note. Could you say it again, "
        "or type it?")
UNSUPPORTED = "I can read text messages and listen to voice notes. Photos and files are not something I can open yet."
NOTHING_CHANGED = ("Nothing has changed in your reminders yet: tell me, for example, \"portfolio is finished\", "
                   "and I will ask you to confirm.")
BROKEN = ("Sorry, something went wrong on my side ({kind}), so I could not answer. The details are in "
          ".state\\adviser.log on the laptop.")


@dataclass
class Services:
    """Everything a turn touches; tests swap in fakes."""
    base_dir: str
    env: dict
    client: Client
    store: memory.Store
    portfolio: brain.Portfolio
    pool: brain.ModelPool | None
    transcribe: Callable = speech.transcribe
    render_note: Callable = speech.render_note
    clock: Callable = time.time


class TurnState(TypedDict, total=False):
    batch: list
    to: str
    acked: float
    heard: str
    via: str
    language: str
    conv: dict
    mode: str
    reply: str
    extra: str
    unsaid: str
    handled: bool
    proposed: bool
    silent: bool
    model: str
    trace: list
    sent: list


def _projects_text(portfolio: brain.Portfolio) -> str:
    lines = ["*Your projects*"]
    for p in sorted(portfolio.projects.values(), key=lambda p: p.idle_days):
        when = "worked on today" if p.idle_days == 0 else f"last work {p.idle_days} days ago"
        lines.append(f"- *{p.name}*: {portfolio.status.get(p.name, 'unknown')}, {when}")
    return "\n".join(lines) if len(lines) > 1 else "I could not find any projects."


def build_turn(svc: Services):
    def ack(message_id: str) -> float:
        try:
            svc.client.mark_read(message_id, typing=True)
        except Exception as exc:                      # a missing tick must not cost the answer
            log.warning("Could not mark %s read: %s", message_id, exc)
        return svc.clock()

    def acknowledge(state: TurnState):
        return {"acked": ack(state["batch"][-1].id)}

    def hear(state: TurnState):
        parts, via, language, unsupported, deaf = [], "text", "", False, False
        hint = ""
        for m in state["batch"]:
            if m.kind == "text":
                parts.append(m.text.strip())
            elif m.kind in ("voice", "audio"):
                try:
                    if not hint:
                        try:
                            hint = "Projects: " + ", ".join(svc.portfolio.refresh().names()) + ". " + STT_WORDS
                        except Exception:
                            hint = STT_WORDS
                    audio, mime = svc.client.download(m.media_id)
                    t = svc.transcribe(audio, mime or m.mime, svc.env.get("GROQ_API_KEY", ""), hint=hint)
                    if t.text:
                        parts.append(t.text)
                        via, language = "voice", t.language or language
                        log.info("Heard (%.0fs, %s): %s", t.seconds, t.language or "?", t.text[:200])
                    else:
                        deaf = True
                except Exception as exc:
                    log.warning("Could not transcribe %s: %s", m.id, exc)
                    deaf = True
            elif m.kind == "other":
                unsupported = True
        heard = "\n".join(p for p in parts if p)
        if heard:
            return {"heard": heard, "via": via, "language": language}
        if deaf:
            return {"heard": "", "reply": DEAF, "mode": "text", "handled": True}
        if unsupported:
            return {"heard": "", "reply": UNSUPPORTED, "mode": "text", "handled": True}
        return {"heard": "", "silent": True}              # only reactions: nothing to say

    def after_hear(state: TurnState):
        if state.get("silent"):
            return END
        return "speak" if state.get("handled") else "route"

    def route(state: TurnState):
        conv = svc.store.conversation()
        heard, via = state["heard"], state.get("via", "text")
        sticky = conv.get("mode", "mirror")
        default = (svc.env.get("ADVISER_REPLY_MODE") or "mirror").lower()
        rule = sticky if sticky in ("voice", "text") else default
        if rule == "voice" or (rule != "text" and (via == "voice" or VOICE_ASK.search(heard))):
            mode = "voice"
        else:
            mode = "text"
        out = {"conv": conv, "mode": mode}

        cmd = heard.strip().lower()
        if cmd.startswith("/"):
            word = cmd[1:].split()[0] if len(cmd) > 1 else ""
            if word in ("help", "start"):
                reply = HELP
            elif word in ("reset", "new"):
                svc.store.reset(conv)
                reply = "Fresh start. What would you like to talk about?"
            elif word in ("voice", "call"):
                conv["mode"] = "voice"
                reply = "Okay, I will answer with voice notes from now on. Send /auto to go back."
            elif word == "text":
                conv["mode"] = "text"
                reply = "Okay, text only from now on. Send /auto to go back."
            elif word == "auto":
                conv["mode"] = "mirror"
                reply = "Okay, I will answer a voice note with a voice note and a text with a text."
            elif word == "projects":
                try:
                    reply = _projects_text(svc.portfolio.refresh(force=True))
                except Exception as exc:
                    reply = f"I could not scan your projects: {exc}"
            else:
                reply = f"I do not know /{word}.\n\n{HELP}"
            svc.store.save(conv)
            return {**out, "mode": "text", "reply": reply, "handled": True}

        pending = conv.get("pending")
        if pending:
            answer = yes_or_no(heard)
            svc.store.add(conv, "user", heard, via)
            if answer == "unclear":                     # keep the question open, ask it again
                pending["at"] = svc.clock()
                return {**out, "reply": f"Sorry, I need a clear yes or no. {question_for(pending)}",
                        "handled": True}
            conv["pending"] = None
            if answer == "yes":
                try:
                    said = memory.apply_reminder_change(svc.base_dir, pending["project"], pending["action"],
                                                        pending.get("days", 3))
                    svc.portfolio.invalidate()           # rescan: the project's state just changed
                except Exception as exc:
                    log.exception("Reminder change failed")
                    said = f"I could not change the reminder settings ({type(exc).__name__}), so nothing changed."
                return {**out, "reply": said, "handled": True}
            if answer == "no":
                return {**out, "reply": "Okay, I left your reminders as they are.", "handled": True}
            return out                                   # something else: the proposal lapses
        svc.store.add(conv, "user", heard, via)
        return out

    def after_route(state: TurnState):
        return "speak" if state.get("handled") else "think"

    def think(state: TurnState):
        conv = state["conv"]
        history = conv["messages"][:-1]                   # the new message is added separately
        try:
            if svc.pool is None:
                raise brain.AdviserBusy("no language model configured (GROQ_API_KEY)")
            portfolio = svc.portfolio.refresh()
            briefing = memory.load_briefing(svc.base_dir)
            focus = []
            ref = briefing.get("whatsapp_ref")
            if ref and any(m.reply_to == ref for m in state["batch"]):
                focus.append(f"They are replying to today's WhatsApp reminder, which was about "
                             f"{briefing.get('featured')}.")
            elif briefing.get("featured") and not history and \
                    str(briefing.get("sent_at", ""))[:10] == datetime.fromtimestamp(svc.clock()).date().isoformat():
                focus.append(f"Today's WhatsApp reminder was about {briefing['featured']}.")
            proposal: dict = {}
            tools = brain.make_adviser_tools(portfolio, proposal)
            agent = brain.build_adviser(svc.pool, tools)
            msgs = brain.build_messages(history, state["heard"], state["mode"], portfolio.snapshot(briefing),
                                        datetime.fromtimestamp(svc.clock()), " ".join(focus))
            t0 = svc.clock()
            result = agent.invoke({"messages": msgs}, config={"recursion_limit": 2 * brain.MAX_TOOL_CALLS + 6})
            final = result["messages"][-1]
            text = brain.reply_text(final)
            if not text:
                raise brain.AdviserBusy("the model returned an empty answer")
            say, extra = brain.split_reply(text, state["mode"])
            if state["mode"] == "voice":                  # code is for reading, never for a voice note
                say, code = speech.separate_code(say)
                extra_prose, extra_code = speech.separate_code(extra)
                code = "\n\n".join(c for c in (code, extra_code) if c)
                fenced = f"```\n{code}\n```" if code else ""
                if not say:                               # everything came after the marker
                    say, extra = extra_prose, fenced
                else:
                    extra = "\n\n".join(x for x in (extra_prose, fenced) if x)
            if proposal:                                  # only ever a question; the owner's yes decides
                conv["pending"] = {**proposal, "at": svc.clock()}
                say = confirm_proposal(say, proposal)
            else:
                say, claimed = drop_change_claims(say)
                if claimed:
                    say = f"{say} {NOTHING_CHANGED}".strip()
            trace = brain.tool_trace(result["messages"])
            model = (final.response_metadata or {}).get("adviser_model", "")
            log.info("Answered in %.1fs with %s (%d look-ups: %s)", svc.clock() - t0, model, len(trace),
                     "; ".join(trace)[:300])
            return {"reply": say or extra, "extra": extra if say else "", "model": model, "trace": trace,
                    "proposed": bool(proposal)}
        except Exception as exc:
            log.warning("Adviser failed: %s: %s", type(exc).__name__, str(exc)[:300])
            sorry = BUSY if isinstance(exc, brain.AdviserBusy) else BROKEN.format(kind=type(exc).__name__)
            return {"reply": sorry, "extra": "", "mode": "text"}

    def speak(state: TurnState):
        """The opening sentence or two is made first and sent at once, so the owner hears
        something within seconds; the other notes are made in parallel meanwhile and sent in
        order as each is ready."""
        if state.get("mode") != "voice":
            return {}
        parts = speech.plan_voice(state.get("reply", ""))
        if not parts:
            return {"mode": "text"}
        if svc.clock() - state.get("acked", 0) > RETYPE_AFTER:
            ack(state["batch"][-1].id)
        voice = svc.env.get("ADVISER_VOICE") or speech.DEFAULT_VOICE
        if state.get("language") == "sw":
            voice = svc.env.get("ADVISER_VOICE_SW") or speech.SWAHILI_VOICE
        rate = svc.env.get("ADVISER_VOICE_RATE") or "+0%"
        sent, unsaid = [], []
        workers = ThreadPoolExecutor(max_workers=min(PARALLEL_NOTES, len(parts)))
        try:
            # The opener is made alone first: on a slow connection, notes made alongside it
            # would share the bandwidth and delay the first thing the owner hears.
            jobs = [workers.submit(svc.render_note, parts[0], voice=voice, rate=rate)]
            for i in range(len(parts)):
                try:
                    notes = jobs[i].result(timeout=150)
                    if i == 0:
                        jobs += [workers.submit(svc.render_note, p, voice=voice, rate=rate) for p in parts[1:]]
                    for ogg in notes:
                        sent.append(svc.client.send_voice(state["to"], ogg))
                except BaseException as exc:              # incl. CancelledError from edge-tts's event loop
                    log.warning("Voice note %d of %d failed (%s: %s).", i + 1, len(parts), type(exc).__name__, exc)
                    unsaid = parts[i:]
                    break
        finally:
            # Don't wait for notes still being made after a failure: the text fallback goes now.
            workers.shutdown(wait=False, cancel_futures=True)
        if not sent:
            return {"mode": "text"}                       # deliver sends the whole answer as text
        return {"sent": sent, "unsaid": " ".join(unsaid)}

    def deliver(state: TurnState):
        to, sent = state["to"], list(state.get("sent") or [])
        reply, extra = for_whatsapp(state.get("reply", "")), for_whatsapp(state.get("extra", ""))
        complete = False                                  # did every part of the answer arrive?
        try:
            if state.get("mode") == "voice" and sent:
                rest = "\n\n".join(x for x in (state.get("unsaid", ""), extra) if x)
                if rest:
                    sent.append(svc.client.send_text(to, rest))
            else:
                body = f"{reply}\n\n{extra}".strip() if extra else reply
                sent.append(svc.client.send_text(to, body))
            complete = True
        except Exception as exc:
            log.error("Could not send the reply: %s", exc)
        conv = state.get("conv")
        if conv is not None and state.get("proposed") and not complete:
            conv["pending"] = None      # the question may not have arrived, so a later "ok" must not answer it
        if conv is not None and not state.get("heard", "").startswith("/"):
            if sent:
                svc.store.add(conv, "assistant", f"{reply}\n{extra}".strip(),
                              "voice" if state.get("mode") == "voice" else "text")
            svc.store.save(conv)
        log.info("Replied with %d message(s) (%s).", len(sent), state.get("mode"))
        return {"sent": sent}

    g = StateGraph(TurnState)
    g.add_node("acknowledge", acknowledge)
    g.add_node("hear", hear)
    g.add_node("route", route)
    g.add_node("think", think)
    g.add_node("speak", speak)
    g.add_node("deliver", deliver)
    g.add_edge(START, "acknowledge")
    g.add_edge("acknowledge", "hear")
    g.add_conditional_edges("hear", after_hear, {"route": "route", "speak": "speak", END: END})
    g.add_conditional_edges("route", after_route, {"think": "think", "speak": "speak"})
    g.add_edge("think", "speak")
    g.add_edge("speak", "deliver")
    g.add_edge("deliver", END)
    return g.compile()


def handle(turn_graph, batch: list[Inbound], to: str, apologise=None) -> dict:
    """Run one turn for messages that arrived together (oldest first). Every node already turns
    its own failures into a plainer reply; if the graph itself still breaks, `apologise(to)` sends
    a last-resort message so the owner is not left in silence."""
    try:
        return turn_graph.invoke({"batch": batch, "to": to})
    except BaseException as exc:
        log.exception("Turn crashed")
        if apologise is not None:
            try:
                apologise(to, BROKEN.format(kind=type(exc).__name__))
            except Exception as exc2:
                log.error("Could not even send the apology: %s", exc2)
        return {"error": f"{type(exc).__name__}: {exc}"}
