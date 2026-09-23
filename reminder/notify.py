"""Delivery channels: Gmail SMTP email and the Meta WhatsApp Cloud API.

Standard library only. Payload builders are pure functions so they can be
tested without the network; the send_* functions are thin wrappers.
"""
from __future__ import annotations

import http.client
import json
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

GMAIL_HOST = "smtp.gmail.com"
GMAIL_STARTTLS_PORT = 587
DEFAULT_GRAPH_VERSION = "v26.0"      # newest Graph API version as of 2026-09 (v27.0 doesn't exist yet)
WA_PARAM_MAX = 180          # per variable: 4 full ones plus the template's fixed text must stay under
                            # Meta's 1024-character body limit (error 132005), with room for emoji
USER_AGENT = "second-brain-reminder/1.0"


class DeliveryError(RuntimeError):
    """A channel refused the message. str() is safe to log and to show the owner.

    ``transient`` marks failures that fix themselves (no network, timeouts, 5xx,
    rate limits); those don't use up the day's retry budget. ``code`` is the
    channel's own numeric error code when it gave one (Meta's ``error.code``)."""

    def __init__(self, message: str, transient: bool = False, code: int | None = None):
        super().__init__(message)
        self.transient = transient
        self.code = code


def tls_context() -> ssl.SSLContext:
    """Certificate + hostname verification against the Windows trust store, minus
    Python 3.13's extra RFC 5280 strictness.

    Antivirus HTTPS scanning (Avast Web/Mail Shield on this laptop) re-signs every
    connection with a local root whose Basic Constraints aren't marked critical.
    Windows trusts that root, but VERIFY_X509_STRICT rejects it. Everything else
    is still verified. Gmail is reached on 587/STARTTLS because Avast signs port
    465 with its deliberately *untrusted* root, which must keep failing.
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


# --------------------------------------------------------------------------- email

def build_email(sender: str, to: str, subject: str, text: str, html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Second Brain", sender))
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(user: str, app_password: str, msg: EmailMessage, timeout: float = 30.0) -> None:
    password = re.sub(r"\s+", "", app_password or "")      # Google shows it as "abcd efgh ijkl mnop"
    try:
        with smtplib.SMTP(GMAIL_HOST, GMAIL_STARTTLS_PORT, timeout=timeout) as smtp:
            smtp.ehlo()
            smtp.starttls(context=tls_context())
            smtp.ehlo()
            smtp.login(user, password)
            refused = smtp.send_message(msg)
    # Order matters: every smtplib exception is also an OSError, so the generic
    # network clause must come last.
    except smtplib.SMTPAuthenticationError as exc:
        raise DeliveryError("Gmail rejected the login. Check GMAIL_ADDRESS and that GMAIL_APP_PASSWORD "
                            f"is an App Password, not your normal password ({exc.smtp_code}).") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise DeliveryError(f"Gmail refused recipients: {exc.recipients}") from exc
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as exc:
        raise DeliveryError(f"Email send failed: {type(exc).__name__}: {exc}", transient=True) from exc
    except smtplib.SMTPException as exc:
        code = getattr(exc, "smtp_code", 0) or 0
        # SMTP 4xx = "try again later" by definition; 5xx (or no code) = permanent.
        raise DeliveryError(f"Email send failed: {type(exc).__name__}: {exc}", transient=400 <= code < 500) from exc
    except OSError as exc:                                 # DNS, no network, timeouts
        raise DeliveryError(f"Email send failed: {type(exc).__name__}: {exc}", transient=True) from exc
    if refused:
        raise DeliveryError(f"Gmail refused recipients: {refused}")


# --------------------------------------------------------------------------- whatsapp

# WhatsApp turns *x*, _x_, ~x~ and `x` into formatting and has no escape character. Inside a variable a
# stray mark could pair with the template's own *bold* labels and garble the message. So *, ~ and `
# become look-alike characters, and so does an underscore at the edge of a word (__init__.py). An
# underscore inside a word (test_remind.py) cannot start or end formatting, so it stays as it is.
WA_MARK_LOOKALIKES = {"*": "\u2217", "_": "\uff3f", "~": "\u223c", "`": "\u02cb"}
_WA_MARK = re.compile(r"[*~`]|(?<![^\W_])_|_(?![^\W_])")


def clean_param(value: str, limit: int = WA_PARAM_MAX) -> str:
    """Template variables may not contain newlines, tabs or 4+ consecutive spaces, and must not
    carry WhatsApp formatting marks (see WA_MARK_LOOKALIKES)."""
    s = re.sub(r"[\r\n\t]+", " ", str(value))
    s = re.sub(r" {2,}", " ", s).strip()
    s = _WA_MARK.sub(lambda m: WA_MARK_LOOKALIKES[m.group(0)], s)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s or "-"


def build_whatsapp_template(to: str, template: str, lang: str, params: list[str]) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": re.sub(r"\D", "", to),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": lang},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": clean_param(p)} for p in params],
            }],
        },
    }


def _graph_post(url: str, token: str, payload: dict | None, timeout: float) -> dict:
    """POST when payload is given, GET otherwise."""
    req = urllib.request.Request(
        url, data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        code = None
        try:
            err = json.loads(body).get("error", {})
            if isinstance(err.get("code"), int) and not isinstance(err.get("code"), bool):
                code = err["code"]
            detail = f"code {err.get('code')}: {err.get('message')}"
            if err.get("error_data", {}).get("details"):
                detail += f" ({err['error_data']['details']})"
        except (ValueError, AttributeError):
            detail = body[:300]
        # 429 and 5xx clear up on their own; 4xx (bad token, template, recipient) need the owner.
        raise DeliveryError(f"WhatsApp API HTTP {exc.code}, {detail}",
                            transient=exc.code == 429 or exc.code >= 500, code=code) from exc
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise DeliveryError(f"WhatsApp API unreachable: {type(exc).__name__}: {exc}", transient=True) from exc
    except ValueError as exc:                                  # 200 with a non-JSON body
        raise DeliveryError(f"WhatsApp API returned unreadable JSON: {exc}", transient=True) from exc
    if not isinstance(data, dict):
        raise DeliveryError(f"WhatsApp API returned an unexpected body: {str(data)[:200]}")
    return data


def send_whatsapp(token: str, phone_number_id: str, payload: dict,
                  graph_version: str = DEFAULT_GRAPH_VERSION, timeout: float = 30.0) -> str:
    """Returns the WhatsApp message id. Acceptance is not delivery: a later async
    failure (e.g. the recipient can't be reached) only shows up via webhooks."""
    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
    data = _graph_post(url, token, payload, timeout)
    msgs = data.get("messages") or []
    if not msgs or not msgs[0].get("id"):
        raise DeliveryError(f"WhatsApp API accepted the call but returned no message id: {data}")
    return msgs[0]["id"]


# --------------------------------------------------------------------------- one-time template setup

# Plainly about the owner's own projects and non-promotional, so Meta keeps it in
# the UTILITY category. Variables are never at the start/end and never adjacent.
#
# Layout: WhatsApp shows a TEXT header in bold and a footer in small grey type by
# itself; inside the body *asterisks* make the labels bold. Formatting marks sit on
# fixed label text only, never around a variable, so whatever text fills a variable
# cannot break (or be broken by) the formatting.
# Meta rejects a new template whose body and footer repeat the WORDING of an existing one (the first
# template, "project_checkin", says "Your daily project check-in: {{1}} needs attention ({{2}})..."),
# and one with too little fixed text for its variables. Hence a full opening and closing sentence.
# The header takes no formatting marks (Meta's rule), so it stays plain; WhatsApp shows it in bold.
TEMPLATE_HEADER = "Daily project update"
TEMPLATE_BODY = (
    "Here is today's update on one of your projects.\n\n"
    "\U0001F4CC *Today's project:* {{1}}\n"
    "\u23F3 *Why it is on the list:* {{2}}\n\n"
    "\U0001F4DD *Where you left off:*\n{{3}}\n\n"
    "\U0001F449 *Your next step (about 15 minutes):*\n{{4}}\n\n"
    "Today's email lists every project that needs you, with more details."
)
TEMPLATE_FOOTER = "Sent by your Second Brain"
TEMPLATE_EXAMPLE = ["personal-assistant", "no work for 56 days",
                    "Last edits were in app.py and graph.py.",
                    "Pick up the first open TODO: morning brief scheduler."]
# Meta's answers for "this template cannot be used right now": not approved yet / no such
# name in that language, paused, disabled. Another approved template may still work.
TEMPLATE_UNAVAILABLE = frozenset({132001, 132015, 132016})


def build_template_definition(name: str, lang: str) -> dict:
    return {
        "name": name,
        "language": lang,
        "category": "UTILITY",
        "parameter_format": "positional",
        "components": [
            {"type": "HEADER", "format": "TEXT", "text": TEMPLATE_HEADER},
            {"type": "BODY", "text": TEMPLATE_BODY, "example": {"body_text": [TEMPLATE_EXAMPLE]}},
            {"type": "FOOTER", "text": TEMPLATE_FOOTER},
        ],
    }


def render_template_preview(params: list[str]) -> str:
    """The message roughly as WhatsApp will show it (header bold, footer small), with the
    variables filled in exactly as they are sent. For the dry run; nothing is sent."""
    cleaned = [clean_param(p) for p in params]

    def fill(m):
        i = int(m.group(1))
        return cleaned[i - 1] if 1 <= i <= len(cleaned) else m.group(0)
    body = re.sub(r"\{\{(\d+)\}\}", fill, TEMPLATE_BODY)
    return f"*{TEMPLATE_HEADER}*\n\n{body}\n\n_{TEMPLATE_FOOTER}_"


def create_template(token: str, waba_id: str, name: str, lang: str,
                    graph_version: str = DEFAULT_GRAPH_VERSION) -> dict:
    url = f"https://graph.facebook.com/{graph_version}/{waba_id}/message_templates"
    return _graph_post(url, token, build_template_definition(name, lang), 30.0)


def template_status(token: str, waba_id: str, name: str, graph_version: str = DEFAULT_GRAPH_VERSION) -> list:
    url = (f"https://graph.facebook.com/{graph_version}/{waba_id}/message_templates"
           f"?name={name}&fields=name,status,category,language,rejected_reason")
    return _graph_post(url, token, None, 30.0).get("data", [])


def build_hello_world(to: str) -> dict:
    """Meta's pre-approved test template: proves token, number id and recipient work."""
    return {"messaging_product": "whatsapp", "to": re.sub(r"\D", "", to), "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}}}
