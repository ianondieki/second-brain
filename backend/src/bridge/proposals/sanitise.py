"""The Tier-1 sanitiser (REQ-PROP-02; docs/spec/06 6.1, 6.3). Plain code decides (docs/spec/04 principle 1).

Tier-1 teaser fields (title, problem statement, impact claims, summary) and a developer's new Problem are shown to
every signed-in user, so they are plain text and carry no contact route: contact details belong in the deal room.

- ``plain_text`` turns input into plain text: HTML tags (and script and style blocks, comments) are dropped and
  entities decoded, repeatedly, then Unicode NFKC (full-width letters become ASCII), invisible format and control
  characters are removed and whitespace is tidied.
- ``contact_findings`` finds URLs, bare domains, email addresses (also "name [at] host"), phone numbers (E.164 with
  "+", Kenyan 07xx/01xx and 254 forms, with spaces, dots, hyphens or brackets) and M-Pesa till/paybill numbers.
- ``check_field`` checks the raw and the plain form of one value (a link hidden in HTML is still a link) and, for the
  summary, the 150-word limit. Each error names the field and a plain reason, never the offending text.

Moderation holds (an organisation named negatively, a security vulnerability) are the pre-screen's
(``bridge.proposals.prescreen``), not the sanitiser's: those teasers are held for a moderator, not refused.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

MAX_SUMMARY_WORDS: Final = 150
TIER1_FIELDS: Final = ("title", "problem_statement", "impact_claims", "summary")

# [[COPY-REVIEW]] plain reasons shown next to the field (never the offending text).
_ELSEWHERE = "contact details and links belong in the deal room, not the public teaser."
MESSAGES: Final[Mapping[str, str]] = {
    "contains_url": f"Remove the web address: {_ELSEWHERE}",
    "contains_domain": f"Remove the website or domain name: {_ELSEWHERE}",
    "contains_email": f"Remove the email address: {_ELSEWHERE}",
    "contains_phone": f"Remove the phone number: {_ELSEWHERE}",
    "contains_payment_number": f"Remove the till or paybill number: {_ELSEWHERE}",
}
CODES: Final = tuple(MESSAGES)


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: str
    message: str


# --- plain text ------------------------------------------------------------------------------------------------------

_BLOCKS = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENTS = re.compile(r"<!--.*?-->|<![^>]*>", re.DOTALL)
# A tag starts right after "<" with a letter ("a < b" is text, not a tag).
_TAGS = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?/?>")
_HSPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_KEEP_CONTROLS = frozenset("\n")


def _strip_markup(value: str) -> str:
    for _ in range(3):  # "&lt;b&gt;" decodes to a tag, which the next pass removes
        stripped = html.unescape(_TAGS.sub(" ", _COMMENTS.sub(" ", _BLOCKS.sub(" ", value))))
        if stripped == value:
            break
        value = stripped
    return value


def plain_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = unicodedata.normalize("NFKC", _strip_markup(unicodedata.normalize("NFKC", text)))
    text = "".join(
        ch for ch in text if ch in _KEEP_CONTROLS or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )
    lines = [_HSPACE.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def word_count(text: str) -> int:
    return len(text.split())


# --- contact details -------------------------------------------------------------------------------------------------

_URLS = (
    re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://\S*", re.IGNORECASE),
    re.compile(r"\bwww\d{0,3}\.\S*", re.IGNORECASE),
    re.compile(r"\b(?:mailto|tel|sms|callto|skype|whatsapp):\S*", re.IGNORECASE),
)
_EMAILS = (
    re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE),
    # "jane [at] example (dot) com", "jane (at) gmail"
    re.compile(
        r"\b[a-z0-9._%+-]+\s*[\[({]\s*at\s*[\])}]\s*[a-z0-9-]+"
        r"(?:\s*(?:\.|[\[({]\s*dot\s*[\])}])\s*[a-z0-9-]+)*",
        re.IGNORECASE,
    ),
)
# A curated list: every two-letter code would flag ordinary abbreviations. Kenyan second-level names (co.ke, ac.ke,
# go.ke, or.ke) end in "ke".
_TLDS = (
    "com|net|org|info|biz|io|co|ke|africa|app|dev|ai|me|tech|xyz|online|site|store|shop|gov|edu|ac|uk|us|tz|ug|rw"
    "|ng|za|cloud|digital|link|page|ly|gl|pro|live|world|network|systems|solutions|services|agency|company|website"
)
_DOMAINS = (
    re.compile(rf"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_TLDS})(?![\w-]|\.\w)", re.IGNORECASE),
    re.compile(r"\b[a-z0-9-]+\s*[\[({]\s*dot\s*[\])}]\s*[a-z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z0-9-]+\s+dot\s+(?:co|ac|or|go|ne|sc)\s+dot\s+ke\b", re.IGNORECASE),
)
_SEP = r"[\s.\-()]*"
_PHONES = (
    # Kenyan mobiles: 07xx/01xx, 254 or +254, then nine digits starting 7 or 1, separators anywhere.
    re.compile(rf"(?<![\d+])(?:\(?\+?254\)?|0){_SEP}[17](?:{_SEP}\d){{8}}(?!\d)"),
    # E.164 written with its "+": 8 to 15 digits.
    re.compile(rf"(?<![\w+])\+(?:{_SEP}\d){{8,15}}(?!\d)"),
)
# M-Pesa till and paybill numbers are 5 to 7 digits.
_PAYMENTS = (re.compile(r"\b(?:till|pay\s*bill|buy\s*goods)\b[^\d\n]{0,25}\d(?:[\s-]?\d){4,6}(?!\d)", re.IGNORECASE),)
_DETECTORS: Final = (
    ("contains_url", _URLS),
    ("contains_email", _EMAILS),  # before domains: an address's host is not a second finding
    ("contains_domain", _DOMAINS),
    ("contains_phone", _PHONES),
    ("contains_payment_number", _PAYMENTS),
)


def contact_findings(text: str) -> list[str]:
    """The codes of the contact details in ``text`` (in ``CODES`` order). Each finding is blanked out before the
    next detector runs, so a URL's host or an address's domain is not reported twice."""
    found: set[str] = set()
    for code, patterns in _DETECTORS:
        for pattern in patterns:
            text, hits = pattern.subn(" ", text)
            if hits:
                found.add(code)
    return [code for code in CODES if code in found]


def check_field(field: str, value: str) -> list[FieldError]:
    """The errors of one Tier-1 value (checked raw and as plain text)."""
    plain = plain_text(value)
    raw = unicodedata.normalize("NFKC", value)
    codes = set(contact_findings(raw)) | set(contact_findings(plain))
    errors = [FieldError(field, code, MESSAGES[code]) for code in CODES if code in codes]
    if field == "summary" and (words := word_count(plain)) > MAX_SUMMARY_WORDS:
        message = f"Keep the summary to {MAX_SUMMARY_WORDS} words or fewer (it has {words} now)."
        errors.append(FieldError(field, "too_many_words", message))
    return errors


def sanitise(fields: Mapping[str, str | None]) -> tuple[dict[str, str | None], list[FieldError]]:
    """Plain-text copies of ``fields`` (blank becomes None) and every error, field by field."""
    cleaned: dict[str, str | None] = {}
    errors: list[FieldError] = []
    for field, value in fields.items():
        if value is None:
            cleaned[field] = None
            continue
        errors.extend(check_field(field, value))
        cleaned[field] = plain_text(value) or None
    return cleaned, errors
