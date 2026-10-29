"""Hearing and speaking.

    voice note (OGG/Opus) ──Groq Whisper──▶ text        transcribe()
    reply text ──edge-tts (MP3)──soundfile──▶ OGG/Opus    voice_notes()

Groq's whisper-large-v3-turbo takes WhatsApp's OGG/Opus as it is (free tier: 25 MB
per file, 20 requests/min, 2,000/day). edge-tts uses the same neural voices as
Microsoft Edge's Read Aloud: fluent, free, no key. Its MP3 is re-encoded to
OGG/Opus mono with libsndfile (bundled with the soundfile wheel), so ffmpeg is
not needed. WhatsApp only shows a voice note's play button up to 512 KB, so long
answers are split into several notes at sentence boundaries.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from reminder.notify import USER_AGENT, tls_context

from .whatsapp import error_body, multipart

log = logging.getLogger("adviser")

STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"
STT_MAX_BYTES = 25 * 1024 * 1024
STT_PROMPT_CHARS = 600              # Whisper's prompt is capped at 224 tokens
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
SWAHILI_VOICE = "sw-KE-ZuriNeural"
VOICE_MAX_BYTES = 480_000           # under WhatsApp's 512 KB play-button limit, with headroom
CHUNK_CHARS = 700                   # about 45 seconds of speech, about 200 KB of Opus, ready in about 10
FIRST_CHARS = 260                   # the first note: about 15 seconds, ready in about 5
OPUS_RATES = (8000, 12000, 16000, 24000, 48000)
# WhatsApp's inbound audio types that Whisper accepts, and the file name it needs to see.
STT_NAMES = {"audio/ogg": "voice.ogg", "audio/opus": "voice.ogg", "audio/mpeg": "audio.mp3",
             "audio/mp3": "audio.mp3", "audio/mp4": "audio.m4a", "audio/m4a": "audio.m4a",
             "audio/x-m4a": "audio.m4a", "audio/wav": "audio.wav", "audio/x-wav": "audio.wav",
             "audio/webm": "audio.webm", "audio/flac": "audio.flac"}
LANG_CODES = {"english": "en", "swahili": "sw"}


class SpeechError(RuntimeError):
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass
class Transcript:
    text: str
    language: str = ""          # ISO code when Whisper says, e.g. "en", "sw"
    seconds: float = 0.0


# --------------------------------------------------------------------------- hearing

def transcribe(audio: bytes, mime: str, api_key: str, hint: str = "", model: str = STT_MODEL,
               timeout: float = 60.0, url: str = STT_URL) -> Transcript:
    """`hint` is spelling help for Whisper, e.g. the project names, so "personal assistant"
    comes back as "personal-assistant"."""
    if not api_key:
        raise SpeechError("GROQ_API_KEY is not set, so voice notes cannot be transcribed.")
    base = (mime or "").split(";")[0].strip().lower()
    filename = STT_NAMES.get(base)
    if not filename:
        raise SpeechError(f"This audio type ({base or 'unknown'}) cannot be transcribed. "
                          "Record a WhatsApp voice note instead.")
    if not audio or len(audio) > STT_MAX_BYTES:
        raise SpeechError("The voice note is empty or larger than 25 MB.")
    fields = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if hint:
        fields["prompt"] = hint[:STT_PROMPT_CHARS]
    body, ctype = multipart(fields, {"file": (filename, base, audio)})
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ctype, "User-Agent": USER_AGENT})
    req.add_unredirected_header("Authorization", f"Bearer {api_key}")        # never follows a redirect
    try:
        ctx = tls_context() if url.startswith("https:") else None
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = error_body(exc)[:300]
        raise SpeechError(f"Groq speech-to-text HTTP {exc.code}: {detail}",
                          transient=exc.code == 429 or exc.code >= 500) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SpeechError(f"Groq speech-to-text failed: {type(exc).__name__}: {exc}", transient=True) from exc
    text = str(data.get("text") or "").strip() if isinstance(data, dict) else ""
    lang = str(data.get("language") or "").strip().lower() if isinstance(data, dict) else ""
    try:
        seconds = float(data.get("duration") or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    return Transcript(text=text, language=LANG_CODES.get(lang, lang[:2]), seconds=seconds)


# --------------------------------------------------------------------------- speaking: text for the ear

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]")
_URL = re.compile(r"https?://\S+|www\.\S+")
_CODE_BLOCK = re.compile(r"```.*?(```|$)", re.S)


def speakable(text: str) -> str:
    """Written reply -> words a voice should say: no markdown marks, links, code or emoji."""
    s = _CODE_BLOCK.sub(" ", text or "")
    s = _URL.sub("the link", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = _EMOJI.sub("", s)
    lines = []
    for line in s.splitlines():
        line = re.sub(r"^\s*(#{1,6}\s+|>\s*|[-*•]\s+|\d+[.)]\s+)", "", line).strip()
        # *bold*, _italic_, ~strike~ at word edges; an underscore inside a word (test_x.py) stays
        line = re.sub(r"(?<![\w*])[*_~]+(?=\S)|(?<=\S)[*_~]+(?![\w*])", "", line)
        if not line:
            continue
        if not re.search(r"[.!?:;,]$", line):
            line += "."
        lines.append(line)
    s = " ".join(lines)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


_FENCE = re.compile(r"```[^\n`]*\n?(.*?)(?:```|$)", re.S)
_CODE_LINE = re.compile(
    r"^\s*(?:from\s+[\w.]+\s+import\b|import\s+\w|def\s+\w+\s*\(|class\s+\w+\s*[(:]|return\b|"
    r"pip3?\s+install\b|python3?\s+\S|py\s+-|npm\s+\w|npx\s+\w|git\s+[a-z]|cd\s+\S|\$\s|>>>|#!|@\w+)"
    r"|[{};]\s*$"                                  # C / JS / JSON line endings
    r"|^\s{4,}\S"                                  # an indented block
    r"|^\s*[\w.\[\]'\"]+\s*[+\-*/]?=\s*\S"          # assignment: x = ..., cfg["a"] += 1
    r"|^\s*[\w.]+\([^)]*\)\s*$")                   # a bare call: scheduler.start()


def separate_code(text: str) -> tuple[str, str]:
    """(prose, code): fenced blocks and lines that look like code or shell commands come out,
    so a voice note never reads `from apscheduler.schedulers import …` aloud."""
    code = [m.group(1).strip("\n") for m in _FENCE.finditer(text or "")]
    prose, loose = [], []
    for line in _FENCE.sub("\n", text or "").splitlines():
        (loose if line.strip() and _CODE_LINE.search(line) else prose).append(line)
    if loose:
        code.append("\n".join(loose))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(prose)).strip(), "\n\n".join(c for c in code if c.strip())


def split_for_voice(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack whole sentences into chunks of at most `limit` characters (a sentence longer
    than that is cut at commas, then at spaces)."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    pieces = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit:
            cut = max(sentence.rfind(", ", 0, limit), sentence.rfind(" ", 0, limit))
            cut = cut if cut > limit // 3 else limit
            pieces.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            pieces.append(sentence)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- speaking: audio

def _edge_tls() -> ssl.SSLContext:
    """edge-tts pins certifi's CA bundle in a module constant; behind antivirus TLS scanning
    (Avast on this laptop) only the Windows store can verify, so swap in the same context
    reminder/notify.py uses. Checked, not assumed: fail loudly if edge-tts renames it."""
    import edge_tts.communicate as comm
    if not isinstance(getattr(comm, "_SSL_CTX", None), ssl.SSLContext):
        raise SpeechError("edge-tts changed its TLS internals; pin edge-tts<8 in requirements.txt.")
    ctx = tls_context()
    comm._SSL_CTX = ctx
    return ctx


def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%", timeout: float = 60.0) -> bytes:
    """MP3 (24 kHz mono) from Microsoft's online neural voices. Runs its own event loop, so
    call it from a worker thread, never from inside a running asyncio loop."""
    import edge_tts
    _edge_tls()

    async def run() -> bytes:
        buf = bytearray()
        comm = edge_tts.Communicate(text, voice, rate=rate, connect_timeout=15, receive_timeout=int(timeout))
        async for chunk in comm.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                buf += chunk["data"]
        return bytes(buf)
    try:
        audio = asyncio.run(asyncio.wait_for(run(), timeout + 15))
    except Exception as exc:
        raise SpeechError(f"Text-to-speech failed: {type(exc).__name__}: {exc}", transient=True) from exc
    if not audio:
        raise SpeechError("Text-to-speech returned no audio.", transient=True)
    return audio


def to_ogg_opus(audio: bytes) -> bytes:
    """Any libsndfile-readable audio (MP3, WAV, FLAC, OGG) -> OGG/Opus, mono, as WhatsApp
    voice notes require."""
    import numpy as np
    import soundfile as sf
    try:
        data, rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
    except Exception as exc:
        raise SpeechError(f"Could not decode the synthesized audio: {exc}") from exc
    mono = data.mean(axis=1)
    if rate not in OPUS_RATES:                        # Opus only takes these; edge-tts gives 24 kHz
        target = min(r for r in OPUS_RATES if r >= min(rate, 48000))
        n = max(int(round(len(mono) * target / rate)), 1)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype("float32")
        rate = target
    out = io.BytesIO()
    sf.write(out, mono, rate, format="OGG", subtype="OPUS")
    return out.getvalue()


def plan_voice(text: str, first: int = FIRST_CHARS, limit: int = CHUNK_CHARS) -> list[str]:
    """Reply text -> the words of each voice note. The first note is short (a sentence or two)
    so it can be synthesized and sent while the rest is still being made: edge-tts runs at
    about twice real time, so a one-minute note takes half a minute to make."""
    pieces = split_for_voice(speakable(text), min(first, limit))
    if not pieces:
        return []
    return pieces[:1] + _balanced(" ".join(pieces[1:]), limit)


def _balanced(text: str, limit: int) -> list[str]:
    """Like split_for_voice, but the notes come out about the same length (70s + 5s becomes
    two of about 37s), so each one is ready before the one before it has finished playing."""
    if not text:
        return []
    n = -(-len(text) // limit)                          # ceil
    if n == 1:
        return [text]
    target = len(text) / n
    chunks, cur = [], ""
    for piece in split_for_voice(text, min(limit, 250)):
        cur = f"{cur} {piece}".strip()
        if len(cur) >= target and len(chunks) < n - 1:
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def render_note(part: str, voice: str = DEFAULT_VOICE, rate: str = "+0%", synth=synthesize) -> list[bytes]:
    """One planned part -> OGG/Opus voice note(s); halves the text if a note would be too big
    for WhatsApp's play button."""
    notes, queue = [], [part]
    while queue:
        piece = queue.pop(0)
        ogg = to_ogg_opus(synth(piece, voice, rate))
        if len(ogg) > VOICE_MAX_BYTES and len(piece) > 200:
            queue[:0] = split_for_voice(piece, max(len(piece) // 2, 200))
            continue
        notes.append(ogg)
    return notes


def voice_notes(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%", synth=synthesize,
                limit: int = CHUNK_CHARS) -> list[bytes]:
    """Reply text -> every voice note, in order (the CLI's `say`; the adviser streams instead)."""
    parts = plan_voice(text, limit=limit)
    if not parts:
        raise SpeechError("Nothing to say.")
    return [ogg for part in parts for ogg in render_note(part, voice, rate, synth)]
