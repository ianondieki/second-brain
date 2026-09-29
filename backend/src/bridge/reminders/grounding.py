"""Is every part of a model's line grounded in the facts? (REQ-REM-01; docs/spec/09 progress reporter: 100% factual
consistency; P6 review MAJOR 1).

An allowlist, not a denylist. A line is read in this order and the first failure names the reason:

1. Titles: a title the facts quote (“…”), written with or without its quotes, is one unit, never checked word by word.
2. Dates: a day with its month ("3 Oct", "3 October 2026", "October 3") is one unit and must be a date of the facts
   (the same day and month, and the same year when one is written). A month without its day, a weekday or any other
   time word (tomorrow, week, morning, soon, …) is refused: the facts give dates only (``invented_date``).
3. Numbers: a count is one unit, a number (digits or a cardinal word) with the noun after it and, when one follows
   ("2 engagements are at risk"), its status; it must be a count of the facts (a count written without a status
   matches the facts' count of that noun). "milestone N" is one unit. Any other number, an amount, an ordinal or a
   quantity word is refused (``invented_number``).
4. Statuses: "on track", "at risk", "off track" and "overdue" only where the facts hold them (``invented_status``).
5. Words: every other word is a word of ``VOCABULARY`` (neutral function words and action verbs; no state verbs such
   as paid, signed, approved, cancelled or expired, no negations, no names) or a word of the facts. A capitalised
   word must be in the facts as written, unless it is a vocabulary word opening a sentence ("Please", "Your")
   (``invented_word``).

The facts are read with the same rules (``Grounding.of``), so a unit matches only what the model was shown. Characters
other than letters, digits, spaces and plain punctuation are the caller's to refuse first (``Grounding.symbol``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Final

Unit = tuple[str, ...]


def _words(text: str) -> list[str]:
    return text.split()


VOCABULARY: Final = frozenset(
    _words("""
    a an the this that these those each every all any some both either another other
    i you your yours yourself it its it's they them their we us our there here what which who whose where when how
    you're you've we're that's there's here's what's let's
    to for of in on at by with from before into onto over through until within about as up out
    and or but so then than if while because
    is are be being been am was were has have had do does did can could will would should must need needs let
    check look open review work keep take make get go see start continue focus pick plan prepare move find give try
    stay remember note follow head finish read reply respond
    today now next still just only also too please ready quick quickly good great busy steady well more most very
    again same simple key main top important priority attention progress update updates step steps thing things item
    items task tasks tracker list hello hi
    """)
)
MONTHS: Final = {
    **{m: n for n, m in enumerate(_words("jan feb mar apr may jun jul aug sep oct nov dec"), start=1)},
    **{
        m: n
        for n, m in enumerate(
            _words("january february march april may june july august september october november december"), start=1
        )
    },
    "sept": 9,
}
TIME_WORDS: Final = frozenset(
    _words("""
    monday tuesday wednesday thursday friday saturday sunday tomorrow yesterday tonight week weeks weekly weekend
    month months monthly year years yearly day days daily hour hours minute minutes morning afternoon evening night
    noon midnight soon later earlier ago fortnight
    """)
)
CARDINALS: Final = {
    **{
        w: n
        for n, w in enumerate(
            _words(
                "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
                " sixteen seventeen eighteen nineteen"
            )
        )
    },
    **{w: 10 * n for n, w in enumerate(_words("twenty thirty forty fifty sixty seventy eighty ninety"), start=2)},
}
QUANTITY_WORDS: Final = frozenset(
    _words("""
    first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth last hundred thousand million
    billion dozen couple several few many multiple half double twice once percent
    """)
)
STATUSES: Final = ("on track", "at risk", "off track", "overdue")
COPULAS: Final = frozenset({"is", "are", "was", "were", "be"})
_SENTENCE_BREAKS: Final = frozenset(".!?:;")
_APOSTROPHES: Final = str.maketrans({0x2018: "'", 0x2019: "'"})
PUNCTUATION: Final = frozenset(" .,;:!?'\"“”‘’()-–—")  # noqa: RUF001 - the typographic quotes and dashes are meant

_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b\.?(?:,?\s+(\d{{4}}))?(?!\d)", re.I)
_DATE_MD = re.compile(rf"\b({_MONTH})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?(?!\d)", re.I)
_QUOTED = re.compile(r"“([^”]{1,200})”")
_TOKEN = re.compile(
    r"(?P<title>\d+)|(?P<date>\d+)|(?P<num>\d+(?:[.,]\d+)*)"
    r"|(?P<word>[A-Za-z]+(?:'[A-Za-z]+)*)|(?P<punct>[^\sA-Za-z0-9])"
)


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str  # title | date | num | word | punct
    text: str
    initial: bool  # opens a sentence


@dataclass
class Parsed:
    """A text read into units (titles, dates, counts, milestones) and the words left over."""

    units: set[Unit] = field(default_factory=set)
    words: list[tuple[str, bool]] = field(default_factory=list)  # (word, opens a sentence)
    stray_numbers: int = 0  # numbers that are no unit, amounts and quantity words
    time_words: int = 0  # months without a day, weekdays and other time words


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_APOSTROPHES)


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _number(token: _Token) -> int | None:
    if token.kind == "num" and token.text.isdigit():
        return int(token.text)
    if token.kind == "word":
        return CARDINALS.get(token.text.lower())
    return None


def _status_at(tokens: list[_Token], k: int) -> tuple[str, int] | None:
    words = [t.text.lower() for t in tokens[k : k + 2] if t.kind == "word"]
    for status in STATUSES:
        parts = status.split()
        if words[: len(parts)] == parts and all(t.kind == "word" for t in tokens[k : k + len(parts)]):
            return status, len(parts)
    return None


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    initial = True
    for match in _TOKEN.finditer(text):
        kind = next(name for name, value in match.groupdict().items() if value is not None)
        value = match.group(kind)
        if kind == "punct":
            tokens.append(_Token("punct", value, False))
            initial = initial or value in _SENTENCE_BREAKS
            continue
        tokens.append(_Token(kind, value, initial))
        initial = False
    return tokens


def parse(text: str, titles: tuple[str, ...]) -> Parsed:
    """``text`` read into units, with ``titles`` (longest first) taken out whole."""
    text = _normal(text)
    parsed = Parsed()
    for index, title in enumerate(titles):
        pattern = re.compile(r"[“\"]?" + re.escape(title) + r"[”\"]?")
        text, found = pattern.subn(f" {index} ", text)
        if found:
            parsed.units.add(("title", title))
    dates: list[Unit] = []

    def keep(day: str, month: str, year: str | None) -> str:
        dates.append(("date", str(int(day)), str(MONTHS[month.lower()]), year or ""))
        return f" {len(dates) - 1} "

    text = _DATE_DM.sub(lambda m: keep(m.group(1), m.group(2), m.group(3)), text)
    text = _DATE_MD.sub(lambda m: keep(m.group(2), m.group(1), m.group(3)), text)
    parsed.units.update(dates)
    tokens = _tokens(text)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        lower = token.text.lower()
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        n = _number(token)
        if token.kind in ("title", "date"):
            i += 1
        elif token.kind == "word" and lower in ("milestone", "milestones") and following and _number(following):
            parsed.units.add(("milestone", str(_number(following))))
            i += 2
        elif n is not None and following is not None and following.kind == "word":
            j = i + 2
            k = j + 1 if j < len(tokens) and tokens[j].text.lower() in COPULAS else j
            status = _status_at(tokens, k)
            if status is not None:
                j = k + status[1]
            parsed.units.add(("count", str(n), _singular(following.text.lower()), status[0] if status else ""))
            i = j
        elif n is not None or token.kind == "num" or lower in QUANTITY_WORDS:
            parsed.stray_numbers += 1
            i += 1
        elif token.kind == "word" and (lower in MONTHS or lower in TIME_WORDS):
            parsed.time_words += 1
            i += 1
        else:
            if token.kind == "word":
                parsed.words.append((token.text, token.initial))
            i += 1
    return parsed


@dataclass(frozen=True)
class Grounding:
    """What the facts hold: their units, titles, statuses and words."""

    titles: tuple[str, ...]
    units: frozenset[Unit]
    statuses: frozenset[str]
    exact: frozenset[str]
    lower: frozenset[str]

    @classmethod
    def of(cls, facts: str) -> Grounding:
        normal = _normal(facts)
        titles = tuple(sorted(set(_QUOTED.findall(normal)), key=len, reverse=True))
        parsed = parse(normal, titles)
        words = [w for w, _ in parsed.words] + [w for title in titles for w in re.findall(r"[A-Za-z]+", title)]
        lowered = normal.lower()
        return cls(
            titles=titles,
            units=frozenset(parsed.units),
            statuses=frozenset(s for s in STATUSES if re.search(rf"\b{s}\b", lowered)),
            exact=frozenset(words),
            lower=frozenset(w.lower() for w in words),
        )

    def symbol(self, text: str) -> bool:
        """True when ``text`` holds a character other than letters, digits and plain punctuation (titles aside)."""
        text = _normal(text)
        for title in self.titles:
            text = text.replace(title, " ")
        return any(not (ch.isalnum() and ch.isascii()) and ch not in PUNCTUATION for ch in text)

    def _date_known(self, unit: Unit) -> bool:
        _, day, month, year = unit
        return any(u[0] == "date" and u[1] == day and u[2] == month and (not year or u[3] == year) for u in self.units)

    def _count_known(self, unit: Unit) -> bool:
        _, n, noun, status = unit
        return any(
            u[0] == "count" and u[1] == n and u[2] == noun and (not status or u[3] == status) for u in self.units
        )

    def problem(self, text: str) -> str | None:
        """Why ``text`` is not grounded in the facts (see the module docstring), or None."""
        parsed = parse(text, self.titles)
        dates = [u for u in parsed.units if u[0] == "date"]
        if parsed.time_words or not all(self._date_known(u) for u in dates):
            return "invented_date"
        counts = [u for u in parsed.units if u[0] == "count"]
        milestones = [u for u in parsed.units if u[0] == "milestone"]
        if parsed.stray_numbers or not all(self._count_known(u) for u in counts):
            return "invented_number"
        if not all(u in self.units for u in milestones):
            return "invented_number"
        lowered = _normal(text).lower()
        if any(re.search(rf"\b{s}\b", lowered) and s not in self.statuses for s in STATUSES):
            return "invented_status"
        for word, initial in parsed.words:
            if word[:1].isupper():
                grounded = word in self.exact or (initial and word.lower() in VOCABULARY)
            else:
                grounded = word in VOCABULARY or word in self.lower
            if not grounded:
                return "invented_word"
        return None

    def covers(self, fact: str, written: str) -> bool:
        """True when ``written`` keeps every title, date, milestone and count of ``fact`` (a date's year may go)."""
        kept = parse(written, self.titles).units
        for unit in parse(fact, self.titles).units:
            if unit[0] == "date":
                if not any(u[0] == "date" and u[1:3] == unit[1:3] and u[3] in ("", unit[3]) for u in kept):
                    return False
            elif unit not in kept:
                return False
        return True
