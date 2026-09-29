"""The Tier-1 sanitiser (REQ-PROP-02; docs/spec/06 6.1, 6.3). Plain code decides (docs/spec/04 principle 1).

Tier-1 teaser fields (title, problem statement, impact claims, summary) and a developer's new Problem are shown to
every signed-in user, so they are plain text and carry no contact route: contact details belong in the deal room.

- ``plain_text`` turns input into plain text: HTML tags (and script and style blocks, comments) are dropped and
  entities decoded, repeatedly, then Unicode NFKC (full-width letters become ASCII), invisible format and control
  characters are removed and whitespace is tidied.
- ``detection_skeleton`` is what the detectors read (never what is stored): NFKD without combining marks, Cyrillic,
  Greek and Armenian lookalikes of Latin letters mapped to ASCII, blank-rendering fillers (Hangul, Braille) dropped,
  ideographic and other full stops mapped to ".", every Unicode decimal digit mapped to ASCII, and defanged forms
  ("[.]", "(dot)", "x . com", "[at]") turned back into "." and "@".
- ``contact_findings`` finds URLs, bare domains, email addresses (also "name @ host", "@host.tld" and "name [at]
  host"), phone numbers (E.164 with "+", Kenyan 07xx/01xx and 254 forms, with spaces, dots, hyphens, slashes, commas,
  underscores or brackets) and M-Pesa till/paybill numbers (keyword before or after the number).
- ``check_field`` checks the skeletons of the raw and the plain form of one value (a link hidden in HTML is still a
  link), the field's length after cleaning (NFKC can lengthen text) and, for the summary, the 150-word limit. Each
  error names the field and a plain reason, never the offending text.

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
# Characters after cleaning (the columns' sizes where they have one); the request models use the same numbers.
MAX_LENGTHS: Final[Mapping[str, int]] = {
    "title": 120,
    "problem_statement": 2000,
    "impact_claims": 1000,
    "summary": 1500,
    "new_problem.title": 90,
    "new_problem.statement": 2000,
}

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


# Characters that render as blank space but are letters or symbols to Unicode (so no whitespace rule sees them).
_BLANKS: Final = frozenset("\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0")
_WORDS = re.compile(r"\w[\w'-]*")


def word_count(text: str) -> int:
    return len(_WORDS.findall("".join(" " if ch in _BLANKS else ch for ch in text)))


# --- the detection skeleton ------------------------------------------------------------------------------------------

# Lookalikes of Latin letters (Unicode confusables, Cyrillic, Greek and Armenian), for detection only.
# (lookalikes, the ASCII letters they imitate), pairwise: Cyrillic lower and upper case, Greek lower and upper case,
# then Armenian and Latin variants.
_LOOKALIKES: Final = (
    (
        "\u0430\u0441\u0501\u0435\u04bb\u0456\u0458\u04cf\u043e\u0440\u051b\u0455\u051d\u0445\u0443\u04af",
        "acdehijlopqswxyy",
    ),
    ("\u043a\u043c\u0442\u043d\u043f\u044c\u0451", "kmthnbe"),
    (
        "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0423\u0406\u0408\u0405\u04ae",
        "ABEKMHOPCTXYIJSY",
    ),
    ("\u03b1\u03bf\u03c1\u03bd\u03c5\u03b9\u03ba\u03c4\u03c7\u03b5\u03b3\u03f2\u03f3", "aopvuiktxeycj"),
    ("\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7", "ABEZHIKMNOPTYX"),
    ("\u0585\u057d\u0570\u0578\u0131\u0261\u0251", "ouhniga"),
)
_CONFUSABLES: Final = str.maketrans({k: v for keys, values in _LOOKALIKES for k, v in zip(keys, values, strict=True)})
_DOTS: Final = frozenset("\u3002\uff0e\uff61\ufe52\u2024")
_DEFANGED_DOT = re.compile(r"\s*[\[({]\s*(?:\.|dot)\s*[\])}]\s*|(?<=\w) \. (?=\w)", re.IGNORECASE)
_DEFANGED_AT = re.compile(r"\s*[\[({]\s*at\s*[\])}]\s*", re.IGNORECASE)


def _skeleton_char(ch: str, blank: str) -> str:
    if ch in _BLANKS:
        return blank
    if ch in _DOTS:
        return "."
    category = unicodedata.category(ch)
    if category in ("Mn", "Me", "Cf"):
        return ""
    if category == "Nd":
        return str(unicodedata.decimal(ch))
    return ch


def detection_skeleton(text: str, *, blank: str = "") -> str:
    """The text the detectors read: lookalikes, fillers, foreign full stops and digits, and defanged forms turned into
    what they stand for. Never stored or shown. Fillers are dropped (``coldchain<filler>.com`` is a domain); the
    pre-screen passes ``blank=" "`` because a filler between words separates them."""
    text = "".join(_skeleton_char(ch, blank) for ch in unicodedata.normalize("NFKD", text)).translate(_CONFUSABLES)
    return _DEFANGED_AT.sub("@", _DEFANGED_DOT.sub(".", text))


# --- contact details -------------------------------------------------------------------------------------------------

_URLS = (
    re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://\S*", re.IGNORECASE),
    re.compile(r"\bwww\d{0,3}\.\S*", re.IGNORECASE),
    re.compile(r"\b(?:mailto|tel|sms|callto|skype|whatsapp):\S*", re.IGNORECASE),
)
_EMAILS = (
    re.compile(r"[a-z0-9._%+-]+@[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)*", re.IGNORECASE),
    # "jane @gmail.com", "jane@ gmail.com", "@gmail.com": an "@" before a domain name, spaced or without a local part.
    re.compile(
        r"(?:[a-z0-9._%+-]+\s*)?@\s*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.IGNORECASE
    ),
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
_SEP = r"[\s.\-()/,_]*"
_PHONES = (
    # Kenyan mobiles: 07xx/01xx, 254 or +254, then nine digits starting 7 or 1, separators anywhere.
    re.compile(rf"(?<![\d+])(?:\(?\+?254\)?|0){_SEP}[17](?:{_SEP}\d){{8}}(?!\d)"),
    # E.164 written with its "+": 8 to 15 digits.
    re.compile(rf"(?<![\w+])\+(?:{_SEP}\d){{8,15}}(?!\d)"),
)
# M-Pesa till and paybill numbers are 5 to 7 digits.
_PAYMENTS = (
    re.compile(r"\b(?:till|pay\s*bill|buy\s*goods)\b[^\d\n]{0,25}\d(?:[\s-]?\d){4,6}(?!\d)", re.IGNORECASE),
    re.compile(r"(?<!\d)\d(?:[\s-]?\d){4,6}(?!\d)[\s:(),.-]{0,5}(?:till|pay\s*bill|buy\s*goods)\b", re.IGNORECASE),
)
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
    codes = set(contact_findings(detection_skeleton(raw))) | set(contact_findings(detection_skeleton(plain)))
    errors = [FieldError(field, code, MESSAGES[code]) for code in CODES if code in codes]
    if (limit := MAX_LENGTHS.get(field)) is not None and len(plain) > limit:
        errors.append(FieldError(field, "too_long", f"Keep this to {limit} characters or fewer."))
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
