"""WhatsApp Cloud API, the two-way half.

Inbound: webhook verification (GET), the X-Hub-Signature-256 check (POST) and
turning Meta's nested payload into flat `Inbound` messages. Outbound: the
free-form messages the adviser may send inside the 24-hour customer-service
window that the owner's own message opens (text, voice notes, the read receipt
with a typing indicator), plus media download and upload.

Standard library only, like reminder/notify.py. Payload builders and the parser
are pure functions; `Client` is a thin wrapper over HTTP.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

from reminder.notify import DEFAULT_GRAPH_VERSION, USER_AGENT, DeliveryError, tls_context

GRAPH_BASE = "https://graph.facebook.com"
TEXT_MAX = 4096                     # Meta's limit for a text message body
MAX_MEDIA_BYTES = 16 * 1024 * 1024  # WhatsApp's own audio limit; Groq's free tier takes up to 25 MB
# Media download URLs come back from the Graph API; the access token is only ever sent to Meta's hosts.
MEDIA_HOSTS = (".fbsbx.com", ".facebook.com", ".whatsapp.net", ".fbcdn.net")


# --------------------------------------------------------------------------- inbound

@dataclass
class Inbound:
    """One message the owner sent. `kind` is text | voice | audio | reaction | other."""
    id: str
    sender: str                 # digits only, e.g. 254770524512
    timestamp: int
    kind: str
    text: str = ""              # text body, button label, or (later) the transcript of a voice note
    media_id: str = ""
    mime: str = ""
    reply_to: str = ""          # id of the business message the owner swiped to reply to
    name: str = ""              # WhatsApp profile name
    phone_number_id: str = ""   # the business number it was sent to
    raw_type: str = ""


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Meta signs the raw POST body with the app secret: `X-Hub-Signature-256: sha256=<hex>`."""
    if not app_secret or not header:
        return False
    algo, _, given = header.strip().partition("=")
    if algo.lower() != "sha256" or not given or not given.isascii():
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given.strip().lower())


def verify_challenge(query: dict, verify_token: str) -> str | None:
    """The GET Meta sends when the callback URL is set. Returns hub.challenge to echo back,
    or None when the request is not a valid subscription check."""
    def one(key):
        v = query.get(key, "")
        return v[0] if isinstance(v, list) else v
    token = one("hub.verify_token")
    if one("hub.mode") != "subscribe" or not verify_token or not token:
        return None
    if not hmac.compare_digest(token.encode("utf-8"), verify_token.encode("utf-8")):
        return None
    challenge = one("hub.challenge")
    return challenge if re.fullmatch(r"[\w.-]{1,256}", challenge or "") else None


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _parse_message(m: dict, names: dict, pnid: str) -> Inbound | None:
    if not isinstance(m, dict) or not m.get("id") or not m.get("from"):
        return None
    t = str(m.get("type") or "")
    try:
        ts = int(m.get("timestamp") or 0)
    except (TypeError, ValueError):
        ts = 0
    ctx = m.get("context") if isinstance(m.get("context"), dict) else {}
    msg = Inbound(id=str(m["id"]), sender=_digits(m["from"]), timestamp=ts, kind="other",
                  reply_to=str(ctx.get("id") or ""), name=names.get(str(m["from"]), ""),
                  phone_number_id=pnid, raw_type=t)
    body = m.get(t) if isinstance(m.get(t), dict) else {}
    if t == "text":
        msg.kind, msg.text = "text", str(body.get("body") or "")
    elif t == "audio":
        msg.kind = "voice" if body.get("voice") else "audio"
        msg.media_id, msg.mime = str(body.get("id") or ""), str(body.get("mime_type") or "")
    elif t == "button":                                  # quick-reply button on a template
        msg.kind, msg.text = "text", str(body.get("text") or body.get("payload") or "")
    elif t == "interactive":
        reply = body.get("button_reply") or body.get("list_reply")
        msg.kind, msg.text = "text", str(reply.get("title") or "") if isinstance(reply, dict) else ""
    elif t == "reaction":
        msg.kind, msg.text = "reaction", str(body.get("emoji") or "")
    if msg.kind == "text" and not msg.text.strip():
        msg.kind = "other"
    if msg.kind in ("voice", "audio") and not msg.media_id:
        msg.kind = "other"
    return msg


def parse_webhook(payload) -> tuple[list[Inbound], list[dict]]:
    """(messages, statuses) from a `messages` webhook. Never raises on odd shapes: anything it
    does not understand is skipped, because the endpoint must still answer 200."""
    messages, statuses = [], []
    if not isinstance(payload, dict):
        return messages, statuses

    def items(x):
        return x if isinstance(x, list) else []

    for entry in items(payload.get("entry")):
        if not isinstance(entry, dict):
            continue
        for change in items(entry.get("changes")):
            try:                                      # one odd change must not lose the others
                if not isinstance(change, dict) or change.get("field") != "messages":
                    continue
                value = change.get("value") if isinstance(change.get("value"), dict) else {}
                meta = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
                pnid = str(meta.get("phone_number_id") or "")
                names = {}
                for c in items(value.get("contacts")):
                    profile = c.get("profile") if isinstance(c, dict) and isinstance(c.get("profile"), dict) else {}
                    if isinstance(c, dict):
                        names[str(c.get("wa_id"))] = str(profile.get("name") or "")
                for m in items(value.get("messages")):
                    try:
                        parsed = _parse_message(m, names, pnid)
                    except (AttributeError, TypeError, ValueError):
                        parsed = None
                    if parsed:
                        messages.append(parsed)
                statuses.extend(s for s in items(value.get("statuses")) if isinstance(s, dict))
            except (AttributeError, TypeError, ValueError):
                continue
    return messages, statuses


# --------------------------------------------------------------------------- outbound payloads

def for_whatsapp(text: str) -> str:
    """Markdown habits -> WhatsApp formatting. Models write **bold**, # headings and [a](b)
    links even when told not to; WhatsApp would show the extra marks literally. ```code```
    blocks (WhatsApp shows them in monospace) are left exactly as they are."""
    spans: list[str] = []

    def hide(m):                                          # code is set aside and put back untouched
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"
    s = _CODE_SPAN.sub(hide, (text or "").replace("\x00", ""))
    s = re.sub(r"^([ \t]*)[*+][ \t]+", r"\1- ", s, flags=re.M)              # "* item" would start bold
    # "## Heading" -> bold line; "#1 priority" and "C#" are not headings
    s = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", r"*\1*", s, flags=re.M)
    s = re.sub(r"(?<![\w*])\*{2,3}(?=\S)(.+?)(?<=\S)\*{2,3}(?![\w*])", r"*\1*", s)   # **bold** (not 2**10)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", s)
    s = re.sub(r"[ \t]+\n", "\n", s)                                          # markdown hard breaks
    s = re.sub(r"\n{3,}", "\n\n", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], s).strip()


# ```fenced``` blocks (an unclosed one, from a reply cut short, runs to the end) and `inline` code
_CODE_SPAN = re.compile(r"```.*?(?:```|\Z)|`[^`\n]+`", re.S)


def build_text(to: str, body: str) -> dict:
    body = body.strip() or "…"
    if len(body) > TEXT_MAX:
        body = body[: TEXT_MAX - 1].rstrip() + "…"
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": _digits(to),
            "type": "text", "text": {"body": body, "preview_url": False}}


def build_voice(to: str, media_id: str) -> dict:
    """`voice: true` makes WhatsApp show it as a voice note (play button, waveform,
    transcript) instead of an audio file. It must be OGG/Opus, mono, and at most 512 KB
    for the play button to appear."""
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": _digits(to),
            "type": "audio", "audio": {"id": media_id, "voice": True}}


def build_read(message_id: str, typing: bool = True) -> dict:
    """Blue ticks for the owner's message (and every earlier one), plus 'typing…' for up to
    25 seconds or until the reply arrives."""
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    return payload


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """files: name -> (filename, content_type, bytes). Returns (body, content-type header)."""
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n").encode("utf-8")
    for name, (filename, ctype, data) in files.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- client

def error_body(exc: urllib.error.HTTPError, limit: int = 65536) -> str:
    """The body of an HTTP error response, or "" if the connection drops while reading it
    (seen on Windows as ConnectionResetError); the status code alone must still get through."""
    try:
        return exc.read(limit).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException):
        return ""


def _meta_error(exc: urllib.error.HTTPError) -> DeliveryError:
    body = error_body(exc)
    code = None
    try:
        err = json.loads(body).get("error", {})
        if isinstance(err.get("code"), int) and not isinstance(err.get("code"), bool):
            code = err["code"]
        detail = f"code {err.get('code')}: {err.get('message')}"
        if (err.get("error_data") or {}).get("details"):
            detail += f" ({err['error_data']['details']})"
    except (ValueError, AttributeError):
        detail = body[:300]
    return DeliveryError(f"WhatsApp API HTTP {exc.code}, {detail}",
                         transient=exc.code == 429 or exc.code >= 500, code=code)


class Client:
    """The business number's side of the conversation. `base` is only changed by tests."""

    def __init__(self, token: str, phone_number_id: str, graph_version: str = DEFAULT_GRAPH_VERSION,
                 base: str = GRAPH_BASE, timeout: float = 30.0):
        self.token, self.pnid, self.version = token, phone_number_id, graph_version
        self.base, self.timeout = base.rstrip("/"), timeout

    @classmethod
    def from_env(cls, env: dict) -> "Client":
        return cls(env["WA_ACCESS_TOKEN"], env["WA_PHONE_NUMBER_ID"],
                   env.get("WA_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION,
                   env.get("WA_GRAPH_BASE") or GRAPH_BASE)

    def _url(self, path: str) -> str:
        return f"{self.base}/{self.version}/{path.lstrip('/')}"

    def _open(self, req: urllib.request.Request) -> tuple[bytes, str]:
        # Unredirected: urllib copies ordinary headers onto a redirect, which could hand the
        # token to whatever host a redirect names.
        req.add_unredirected_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", USER_AGENT)
        ctx = tls_context() if req.full_url.startswith("https:") else None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                return resp.read(MAX_MEDIA_BYTES + 1), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise _meta_error(exc) from exc
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            raise DeliveryError(f"WhatsApp API unreachable: {type(exc).__name__}: {exc}", transient=True) from exc

    def _json(self, req: urllib.request.Request) -> dict:
        raw, _ = self._open(req)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError as exc:
            raise DeliveryError(f"WhatsApp API returned unreadable JSON: {exc}", transient=True) from exc
        if not isinstance(data, dict):
            raise DeliveryError(f"WhatsApp API returned an unexpected body: {str(data)[:200]}")
        return data

    def post(self, payload: dict) -> dict:
        req = urllib.request.Request(self._url(f"{self.pnid}/messages"), method="POST",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        return self._json(req)

    def send(self, payload: dict) -> str:
        data = self.post(payload)
        msgs = data.get("messages") or []
        if not msgs or not isinstance(msgs[0], dict) or not msgs[0].get("id"):
            raise DeliveryError(f"WhatsApp API accepted the call but returned no message id: {data}")
        return msgs[0]["id"]

    def mark_read(self, message_id: str, typing: bool = True) -> None:
        self.post(build_read(message_id, typing))

    def _trusted(self, url: str) -> bool:
        u, base = urllib.parse.urlsplit(url), urllib.parse.urlsplit(self.base)
        if (u.scheme, u.netloc) == (base.scheme, base.netloc):
            return True
        host = (u.hostname or "").lower()
        return u.scheme == "https" and any(host.endswith(h) for h in MEDIA_HOSTS)

    def download(self, media_id: str) -> tuple[bytes, str]:
        """GET /{media-id} for a 5-minute URL, then GET that URL with the token."""
        info = self._json(urllib.request.Request(self._url(f"{urllib.parse.quote(media_id)}"
                                                           f"?phone_number_id={self.pnid}")))
        url, mime = str(info.get("url") or ""), str(info.get("mime_type") or "")
        try:
            size = int(info.get("file_size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > MAX_MEDIA_BYTES:
            raise DeliveryError(f"Media is {size:,} bytes; the limit is {MAX_MEDIA_BYTES:,}.")
        if not url or not self._trusted(url):
            raise DeliveryError(f"Refusing to download media from an unexpected address: {url[:120]!r}")
        data, ctype = self._open(urllib.request.Request(url))
        if len(data) > MAX_MEDIA_BYTES:
            raise DeliveryError("Media is larger than the limit.")
        return data, (mime or ctype.split(";")[0].strip())

    def upload(self, data: bytes, mime: str, filename: str) -> str:
        body, ctype = multipart({"messaging_product": "whatsapp", "type": mime},
                                {"file": (filename, mime, data)})
        req = urllib.request.Request(self._url(f"{self.pnid}/media"), data=body, method="POST",
                                     headers={"Content-Type": ctype})
        media_id = str(self._json(req).get("id") or "")
        if not media_id:
            raise DeliveryError("WhatsApp accepted the upload but returned no media id.")
        return media_id

    def send_text(self, to: str, body: str) -> str:
        return self.send(build_text(to, body))

    def send_voice(self, to: str, ogg: bytes) -> str:
        return self.send(build_voice(to, self.upload(ogg, "audio/ogg", "reply.ogg")))
