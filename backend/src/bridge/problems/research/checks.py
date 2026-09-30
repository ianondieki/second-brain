"""The research agent's checks in code (REQ-RES-01; docs/spec/06 6.5; AC-RES-1; D-45). The model drafts; this module
decides whether a draft becomes a candidate card, and whether a candidate may be published.

A draft (``Draft``, the model's answer after parsing) is kept only when, in this order:

1. **Text.** NFKC and whitespace collapsed (the revision 0005 operating rule), then no control or format character,
   a title of 1 to 90 characters, a statement of 1 to 120 words and at most 1500 characters, an affected group of at
   most 200 characters, at most 10 named organisations of at most 200 characters (``text_out_of_bounds``,
   ``control_character``).
2. **Citations.** At least one (``no_citation``); every cited id is one of the excerpts this run sent, else the whole
   draft is discarded (``unknown_excerpt``: the model invented a source). A citation counts only when its supporting
   text (at least ``min_support_words`` words) appears verbatim in the excerpt's quote after whitespace collapsing,
   Unicode-exact; an unverified citation is dropped and lowers the extraction agreement; none left is
   ``no_verified_citation``.
3. **Numbers.** Every number in the title, statement, affected group and named organisations appears in a cited
   quote with the same scale (``unsupported_number``): digits (``2,000`` is 2000; ``11.6`` is not 11) and the number
   words two to ninety; letters glued to a number are its scale ("Sh15m" is 15 million, "89B" 89 billion, an unknown
   suffix such as "4G" matches only itself), and after a space the scale words percent, percentage points,
   thousand, million, billion, trillion and their abbreviations; a bare number needs a bare one. So figures from two
   excerpts are never merged, rounded or averaged into a new one (ke-hlt-001's Sh11 billion and ke-hlt-002's
   Sh11.6 billion stay apart), and "89 percent" never supports "Sh89m".
4. **Named organisations (D-45 default (a)).** The organisations of the allowlist (and every publisher) found in the
   text as whole words, plus whatever the model listed in ``named_orgs``: a card naming any needs an official cited
   source (``named_org_without_official``). Detection runs on the NFKC text with format characters ignored, in any
   case, a hyphen matching any dash, a space or nothing; the model's own list is the second net; the approval screen
   shows the names with the checklist placeholder.
5. **Sources (AC-RES-1).** One official cited source (an allowlisted government or regulator domain) or two
   independent publishers (the allowlist's publisher, so one publisher's two domains are one)
   (``needs_official_or_two_publishers``).
6. **Confidence** (docs/spec/06 6.5, weights and tiers from ``policy.yaml``): ``0.35 source_quality + 0.25
   corroboration + 0.20 freshness + 0.20 extraction_agreement``, where source quality is the mean tier of the cited
   sources, corroboration the distinct publishers over ``corroboration_publishers`` (at most 1), freshness the mean
   freshness score (1 until 12 months, 0 at 18), and extraction agreement the verified share of the citations. Rounded
   down to 3 decimals; below ``discard_below`` (0.40) the draft is discarded (``low_confidence``).

``publish_violation`` repeats 1, 3, 4 and 5 on a stored candidate (its sources matched back to the saved excerpts) so
approval decides on what the card says now, not on what the run once saw.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Final

from bridge.problems.research.policy import ResearchPolicy
from bridge.problems.research.sources import Allowlist, Excerpt, freshness_score
from bridge.problems.research.text import collapse, has_control, normalise, word_count

MAX_TITLE_CHARS: Final = 90
MAX_STATEMENT_WORDS: Final = 120
MAX_STATEMENT_CHARS: Final = 1500
MAX_GROUP_CHARS: Final = 200
MAX_NAMED_ORGS: Final = 10
MAX_ORG_CHARS: Final = 200
CONFIDENCE_QUANTUM: Final = Decimal("0.001")  # problems.confidence is numeric(4,3)

# "one" is left out: it is a pronoun as often as a number ("one of the ...").
_SMALL: Final = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
_TEENS: Final = ("thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")
_TENS: Final = ("thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_NUMBER_WORDS: Final = {word: value for value, word in enumerate((*_SMALL, *_TEENS), start=2)} | {
    word: 30 + 10 * index for index, word in enumerate(_TENS)
}
# A number's scale (P11 review MAJOR 1). Letters glued to digits are always a scale ("Sh15m", "89B", "12.5pc", "4G"):
# a known one is normalised, an unknown one is kept as ``suffix:<letters>`` and matches only the same suffix in a
# quote (fail closed). After a space only these words count ("89 percent", "Sh11 billion", "25 million", "3 k"); any
# other word after a space is not a scale ("Level 4 public", "2029 by").
_SCALES: Final = {
    "%": "percent",
    "percent": "percent",
    "per cent": "percent",
    "pc": "percent",
    "percentage point": "percentage_points",
    "percentage points": "percentage_points",
    "thousand": "thousand",
    "k": "thousand",
    "million": "million",
    "m": "million",
    "mn": "million",
    "billion": "billion",
    "bn": "billion",
    "b": "billion",
    "trillion": "trillion",
    "tn": "trillion",
}
_SPACED: Final = r"%|per\s*cent|percentage\s+points?|percent|pc|thousand|million|billion|trillion|mn|bn|tn|[mbk]"
_LETTER: Final = r"[^\W\d_]"
_NUMBER: Final = re.compile(
    rf"(?P<num>\d+(?:,\d{{3}})*(?:\.\d+)?)(?:(?P<attached>{_LETTER}+|%)|\s*(?P<spaced>{_SPACED})(?!{_LETTER}))?"
    rf"|(?<!{_LETTER})(?P<word>{'|'.join(_NUMBER_WORDS)})(?!{_LETTER})(?:\s*(?P<wscale>{_SPACED})(?!{_LETTER}))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Citation:
    excerpt_id: str
    supporting_text: str


@dataclass(frozen=True, slots=True)
class Draft:
    """One drafted card as the model wrote it (``bridge.problems.research.synthesis.ProblemDraft``)."""

    title: str
    statement: str
    affected_group: str
    named_orgs: tuple[str, ...]
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class CardText:
    title: str
    statement: str
    affected_group: str
    named_orgs: tuple[str, ...]

    @property
    def fields(self) -> tuple[str, ...]:
        return (self.title, self.statement, self.affected_group)


@dataclass(frozen=True, slots=True)
class Accepted:
    text: CardText
    sources: tuple[Excerpt, ...]
    confidence: Decimal
    agreement: Decimal


@dataclass(frozen=True, slots=True)
class Discarded:
    reason: str


Verdict = Accepted | Discarded


# ----------------------------------------------------------------------------------------------------------- text


def clean_text(title: str, statement: str, affected_group: str, named_orgs: Iterable[str]) -> CardText | str:
    """The card's text with whitespace collapsed, or the reason it cannot be stored."""
    names = tuple(dict.fromkeys(n for n in (collapse(name) for name in named_orgs) if n))
    text = CardText(collapse(title), collapse(statement), collapse(affected_group), names)
    if any(has_control(value) for value in (*text.fields, *text.named_orgs)):
        return "control_character"
    if (
        not text.title
        or len(text.title) > MAX_TITLE_CHARS
        or not text.statement
        or word_count(text.statement) > MAX_STATEMENT_WORDS
        or len(text.statement) > MAX_STATEMENT_CHARS
        or len(text.affected_group) > MAX_GROUP_CHARS
        or len(text.named_orgs) > MAX_NAMED_ORGS
        or any(len(name) > MAX_ORG_CHARS for name in text.named_orgs)
    ):
        return "text_out_of_bounds"
    return text


# -------------------------------------------------------------------------------------------------------- numbers


def _value(token: str) -> Decimal | None:
    word = _NUMBER_WORDS.get(token.lower())
    if word is not None:
        return Decimal(word)
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def _scale(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = re.sub(r"\s+", " ", raw.lower())
    return _SCALES.get(key, f"suffix:{key}")


def numbers_in(value: str) -> set[tuple[Decimal, str | None]]:
    """Every (number, scale) in the NFKC form of ``value``; scale is None when no scale follows (see ``_SCALES``)."""
    found: set[tuple[Decimal, str | None]] = set()
    for match in _NUMBER.finditer(normalise(value)):
        number = _value(match.group("num") or match.group("word"))
        if number is None:
            continue
        found.add((number, _scale(match.group("attached") or match.group("spaced") or match.group("wscale"))))
    return found


def unsupported_numbers(fields: Iterable[str], quotes: Iterable[str]) -> list[str]:
    """The numbers in ``fields`` that no quote carries with the same scale: a bare number needs a bare one, "Sh89m"
    needs "89 million" (or "89m"), and "89 percent" never supports "Sh89m" or "89 thousand"."""
    supported: set[tuple[Decimal, str | None]] = set()
    for quote in quotes:
        supported |= numbers_in(quote)
    missing: list[str] = []
    for field in fields:
        for number, scale in sorted(numbers_in(field), key=lambda item: (item[0], item[1] or "")):
            if (number, scale) not in supported:
                missing.append(f"{number}{'' if scale is None else ' ' + scale}")
    return missing


# ------------------------------------------------------------------------------------------------- organisations


# Any dash or hyphen (U+002D, U+2010-U+2015, U+2212 minus), a space, or nothing between an alias's hyphenated parts:
# "M-Pesa", "M\u2011Pesa" (NFKC turns U+2011 into U+2010), "M Pesa" and "MPesa" are one name.
_HYPHEN: Final = r"[\-\u2010-\u2015\u2212\s]?"


def _alias_pattern(alias: str) -> re.Pattern[str]:
    parts = [re.escape(word) for word in re.split(r"[\-\u2010-\u2015\u2212]", normalise(alias))]
    body = _HYPHEN.join(parts).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![^\W_])" + body + r"(?![^\W_])", re.IGNORECASE)


def named_organisations(fields: Iterable[str], declared: Iterable[str], allowlist: Allowlist) -> tuple[str, ...]:
    """The organisations a card names: the allowlist's found in its NFKC text (whole words, any case, any dash) and
    the ones the model declared, each once (case-insensitively), in that order. Matching is deliberately broad: a
    false match discards a draft or asks for the checklist, a missed one would publish a name unchecked (D-45)."""
    text = "".join(c for c in normalise("\n".join(fields)) if unicodedata.category(c) != "Cf")  # no hiding
    found = [org.name for org in allowlist.named() if any(_alias_pattern(a).search(text) for a in org.aliases)]
    names: dict[str, str] = {}
    for name in (*found, *declared):
        names.setdefault(name.casefold(), name)
    return tuple(names.values())


# ------------------------------------------------------------------------------------------------------ sources


def meets_source_rule(sources: Sequence[Excerpt]) -> bool:
    """AC-RES-1: one official source, or two independent publishers."""
    return any(e.official for e in sources) or len({e.publisher for e in sources}) >= 2


def confidence(sources: Sequence[Excerpt], agreement: Decimal, as_of: date, policy: ResearchPolicy) -> Decimal:
    """docs/spec/06 6.5's formula with ``policy.yaml``'s weights, rounded down to 3 decimals."""
    count, full = Decimal(len(sources)), Decimal(policy.corroboration_publishers)
    terms = {
        "source_quality": sum((policy.source_quality[e.source_type] for e in sources), Decimal(0)) / count,
        "corroboration": min(Decimal(1), Decimal(len({e.publisher for e in sources})) / full),
        "freshness": sum((freshness_score(e, as_of, policy) for e in sources), Decimal(0)) / count,
        "extraction_agreement": agreement,
    }
    total = sum((policy.weights[key] * value for key, value in terms.items()), Decimal(0))
    return total.quantize(CONFIDENCE_QUANTUM, rounding=ROUND_FLOOR)


def rule_violation(text: CardText, sources: Sequence[Excerpt]) -> str | None:
    """Numbers, named organisations and the source rule for a card's text and its cited sources."""
    if unsupported_numbers((*text.fields, *text.named_orgs), (e.quote for e in sources)):
        return "unsupported_number"
    if text.named_orgs and not any(e.official for e in sources):
        return "named_org_without_official"
    if not meets_source_rule(sources):
        return "needs_official_or_two_publishers"
    return None


def verified(citation: Citation, excerpt: Excerpt, policy: ResearchPolicy) -> bool:
    support = collapse(citation.supporting_text)
    return word_count(support) >= policy.min_support_words and support in excerpt.quote


def check_draft(
    draft: Draft, sent: Mapping[str, Excerpt], allowlist: Allowlist, policy: ResearchPolicy, as_of: date
) -> Verdict:
    """Whether a drafted card becomes a candidate (see the module docstring for the order of the checks)."""
    cleaned = clean_text(draft.title, draft.statement, draft.affected_group, draft.named_orgs)
    if isinstance(cleaned, str):
        return Discarded(cleaned)
    if not draft.citations:
        return Discarded("no_citation")
    if any(c.excerpt_id not in sent for c in draft.citations):
        return Discarded("unknown_excerpt")
    by_id: dict[str, Citation] = {}
    for citation in draft.citations:
        by_id.setdefault(citation.excerpt_id, citation)
    sources = tuple(sent[i] for i, c in by_id.items() if verified(c, sent[i], policy))
    if not sources:
        return Discarded("no_verified_citation")
    agreement = Decimal(len(sources)) / Decimal(len(by_id))
    names = named_organisations(cleaned.fields, cleaned.named_orgs, allowlist)
    if len(names) > MAX_NAMED_ORGS:
        return Discarded("text_out_of_bounds")
    text = CardText(cleaned.title, cleaned.statement, cleaned.affected_group, names)
    violation = rule_violation(text, sources)
    if violation is not None:
        return Discarded(violation)
    score = confidence(sources, agreement, as_of, policy)
    if score < policy.discard_below:
        return Discarded("low_confidence")
    return Accepted(text, sources, score, agreement)
