"""The trends' checks in code (REQ-DEV-02; D-60; P22 card B, default (5)). The model drafts; this module decides
which drafted trends become candidate cards. The research agent's rules are reused, not copied
(``bridge.problems.research.checks`` and ``bridge.problems.research.text``); what differs is the card's shape (a title
and a summary under a topic) and the named-organisation rule, which every-domain-official sources would otherwise
pass by construction.

The whole answer is refused (``Refused``) when the model flags ``injection_suspected`` (docs/spec/09: nothing of a
flagged answer is used) or drafts no trend (``no_trends``); drafts beyond ``trends.max_cards_per_run`` are discarded
(``over_card_limit``). Each remaining draft is kept only when, in this order (the reason names the first failure):

1. **Text.** NFKC and whitespace collapsed (``collapse``), then no control, format or default-ignorable character in the
   title, summary, named organisations or supports (``control_character``); only Latin letters, ASCII digits and no
   combining marks in the title and summary (``non_latin_text``); no link in the title or summary: a scheme (``://``) or
   a ``www.`` host (``link_in_text``; a host-like token such as ``github.blog`` is refused after step 3 unless a cited
   quote carries it verbatim, so "Node.js" copied from a release note stays); a title of 1 to 120 characters, a summary
   of 1 to 600 characters in two to four sentences, at most 10 named organisations of at most 200 characters and every
   support at most 400 characters (``text_out_of_bounds``; revision 0010's ``trend_cards`` and ``trend_card_sources``
   columns).
2. **Topic.** The ``topic_slug`` is a topic of the excerpts sent in this call (``unknown_topic``).
3. **Citations.** One to five (``no_citation``, ``too_many_citations``: a card has 1-5 sources); every cited
   ``excerpt_ref`` is an excerpt this call sent, else the draft is discarded (``unknown_excerpt``: an invented
   source). A citation counts only when its support (at least ``trends.min_support_words`` words) appears verbatim in
   the excerpt's quote (``research.checks.verified``); an unverified one is dropped and lowers the extraction
   agreement; none left is ``no_verified_citation``; a topic no verified source has is ``topic_not_cited``; a
   host-like token in the title or summary that no cited quote carries is ``link_in_text``.
4. **The research rules** (``research.checks.rule_violation`` on the title and summary): every number with its scale
   in a cited quote (``unsupported_number``); a named organisation needs an official cited source
   (``named_org_without_official``); one official source or two publishers. Every domain of the ``TECH`` allowlist
   is official, so for trends the named-organisation rule is stricter: each organisation the card names (the
   allowlist's found in its text, as the research agent finds them, plus the model's ``named_orgs``) must be named by
   a cited source itself, in its quote or as its publisher (``named_org_without_official``). A vendor named in a quote
   from its own site passes; one named only by the model fails. A name off the allowlist that the model writes
   without declaring it is caught as a capitalised token that no cited quote or publisher, no allowlist name and no
   plain word (``PLAIN_CAPITALISED``: places, months, days, generic acronyms) carries (``unsourced_capitalised``;
   residual: a lower-case brand, or a single-capital one starting a sentence).
5. **Confidence** (``research.checks.confidence``: the research weights and quality tiers, with the trends' ages for
   freshness, ``TrendsPolicy.scoring``); below ``trends.discard_below`` the draft is discarded (``low_confidence``).
   With every source official the floor is source quality plus one publisher's corroboration (0.433 with the shipped
   weights), so the shipped 0.40 discards nothing today; the rule stays for a policy change.

A kept draft carries its verified sources with the support each was verified by, in citation order.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

from bridge.problems.research.checks import (
    MAX_NAMED_ORGS,
    MAX_ORG_CHARS,
    CardText,
    Citation,
    confidence,
    named_organisations,
    rule_violation,
    verified,
)
from bridge.problems.research.policy import ResearchPolicy
from bridge.problems.research.sources import Alias, Allowlist, Excerpt, Organisation
from bridge.problems.research.text import collapse, has_control, non_latin

MAX_TITLE_CHARS: Final = 120  # trend_cards.title
MAX_SUMMARY_CHARS: Final = 600  # trend_cards.summary
MIN_SENTENCES: Final = 2
MAX_SENTENCES: Final = 4
MIN_CITATIONS: Final = 1
MAX_CITATIONS: Final = 5  # a card has 1-5 sources (revision 0010)
MAX_SUPPORT_CHARS: Final = 400  # trend_card_sources.support
# A sentence ends at . ! or ? followed by the end of the text, or by a space and a capital letter, a digit or an
# opening quote: "e.g. the" and "3.15" do not end one, "Go 1.27. The" does.
_SENTENCE_END: Final = re.compile(r"[.!?][\"'\u2019\u201d)]*(?:$|\s+(?=[A-Z0-9\"'\u2018\u201c(]))")
# A link: a scheme separator anywhere or a "www." host (always refused), or a host-like token: dot-separated labels
# whose last label is 2 to 24 letters (the length range of IANA top-level domains), as in "github.blog" or
# "evil.example/login". A host-like token is allowed only when a cited quote carries it verbatim ("Node.js" in a
# release note); "e.g.", "U.S.", "Inc." and version numbers such as "3.15.0rc3" are not host-like.
_SCHEME_OR_WWW: Final = re.compile(r"://|(?<![\w.-])www\.", re.IGNORECASE)
# A capitalised token: a word that starts with a capital letter ("IBM", "GitHub", "Kenya", "S3"); "iPhone" and "npm"
# are not (the residual: an all-lower-case brand is matched only through the allowlist's aliases).
_CAPITALISED: Final = re.compile(r"(?<![\w'\u2019-])[A-Z][A-Za-z0-9]*")
_WORD: Final = re.compile(r"[A-Za-z0-9]+")
# Capitalised words a trend may use without a source naming them: the reader's place, months and days, languages,
# and generic technical acronyms. Not organisations, so not a claim about anyone.
PLAIN_CAPITALISED: Final = frozenset(
    {
        "Kenya", "Kenyan", "Kenyans", "Nairobi", "Africa", "African", "East", "English", "Swahili",
        "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
        "AI", "API", "APIs", "CLI", "SDK", "SDKs", "LLM", "LLMs", "HTTP", "HTTPS", "JSON", "SQL", "CPU", "GPU",
        "IDE", "UI", "CI", "GA", "CVE", "RAG", "EU",
    }
)  # fmt: skip
_HOST_LIKE: Final = re.compile(r"(?<![\w.@-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}(?![\w-])")


class Reason(StrEnum):
    INJECTION_SUSPECTED = "injection_suspected"
    NO_TRENDS = "no_trends"
    OVER_CARD_LIMIT = "over_card_limit"
    CONTROL_CHARACTER = "control_character"
    NON_LATIN_TEXT = "non_latin_text"
    LINK_IN_TEXT = "link_in_text"
    TEXT_OUT_OF_BOUNDS = "text_out_of_bounds"
    UNKNOWN_TOPIC = "unknown_topic"
    NO_CITATION = "no_citation"
    TOO_MANY_CITATIONS = "too_many_citations"
    UNKNOWN_EXCERPT = "unknown_excerpt"
    NO_VERIFIED_CITATION = "no_verified_citation"
    TOPIC_NOT_CITED = "topic_not_cited"
    UNSUPPORTED_NUMBER = "unsupported_number"
    NAMED_ORG_WITHOUT_OFFICIAL = "named_org_without_official"
    NEEDS_OFFICIAL_OR_TWO_PUBLISHERS = "needs_official_or_two_publishers"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True, slots=True)
class TrendDraft:
    """One drafted trend as the model wrote it (``bridge.problems.trends.synthesis.TrendOut``)."""

    title: str
    summary: str
    topic_slug: str
    named_orgs: tuple[str, ...]
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    """The model's whole answer (``TrendSynthesis``)."""

    injection_suspected: bool
    trends: tuple[TrendDraft, ...]


@dataclass(frozen=True, slots=True)
class CitedSource:
    """A verified citation: the saved excerpt as sent and the support (whitespace-collapsed) it was verified by."""

    excerpt: Excerpt
    support: str


@dataclass(frozen=True, slots=True)
class KeptTrend:
    title: str
    summary: str
    topic_slug: str
    named_orgs: tuple[str, ...]
    sources: tuple[CitedSource, ...]
    confidence: Decimal
    agreement: Decimal


@dataclass(frozen=True, slots=True)
class Discarded:
    reason: Reason


@dataclass(frozen=True, slots=True)
class AnswerVerdict:
    """``refused`` is set when nothing of the answer may be used (``injection_suspected``, ``no_trends``) or when no
    draft was kept (then it is the first discarded draft's reason); ``kept`` and ``discarded`` are per draft."""

    kept: tuple[KeptTrend, ...]
    discarded: tuple[Reason, ...]
    refused: Reason | None


def sentence_count(text: str) -> int:
    """Sentences in collapsed text (see ``_SENTENCE_END``); a text without a final stop still counts its last one."""
    text = collapse(text)
    if not text:
        return 0
    ends = list(_SENTENCE_END.finditer(text))
    trailing = 1 if not ends or ends[-1].end() < len(text) else 0
    return len(ends) + trailing


def _text_reason(draft: TrendDraft, title: str, summary: str, names: Sequence[str]) -> Reason | None:
    supports = [collapse(c.supporting_text) for c in draft.citations]
    if any(has_control(v) for v in (title, summary, *names, *supports)):
        return Reason.CONTROL_CHARACTER
    if non_latin(title) or non_latin(summary):
        return Reason.NON_LATIN_TEXT
    if _SCHEME_OR_WWW.search(title) or _SCHEME_OR_WWW.search(summary):
        return Reason.LINK_IN_TEXT
    if (
        not title
        or len(title) > MAX_TITLE_CHARS
        or not summary
        or len(summary) > MAX_SUMMARY_CHARS
        or not MIN_SENTENCES <= sentence_count(summary) <= MAX_SENTENCES
        or len(names) > MAX_NAMED_ORGS
        or any(len(name) > MAX_ORG_CHARS for name in names)
        or any(len(support) > MAX_SUPPORT_CHARS for support in supports)
    ):
        return Reason.TEXT_OUT_OF_BOUNDS
    return None


def unquoted_hosts(fields: Sequence[str], sources: Sequence[Excerpt]) -> tuple[str, ...]:
    """The host-like tokens of ``fields`` (see ``_HOST_LIKE``) that no cited quote carries verbatim."""
    quotes = " ".join(e.quote for e in sources)
    return tuple(
        token
        for field in fields
        for token in _HOST_LIKE.findall(field)
        if re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w-])", quotes) is None
    )


def _sentence_starts(text: str) -> set[int]:
    return {0, *(match.end() for match in _SENTENCE_END.finditer(text))}


def unsourced_capitalised(
    title: str, summary: str, sources: Sequence[Excerpt], allowlist: Allowlist
) -> tuple[str, ...]:
    """Capitalised tokens of the title and summary (``_CAPITALISED``) that may name someone no cited source names: not
    a word of a cited quote or publisher, of an allowlist name, alias or publisher, or of ``PLAIN_CAPITALISED``
    (case-sensitive). A token that starts a sentence (the title is one) counts only when it is shaped like a name
    rather than an ordinary word, with a second capital or a digit ("IBM says", "GitHub now"); "Developers in" does
    not. Residual: a brand written in lower case, or one with a single capital at the start of a sentence ("Oracle
    says"), is caught only through the allowlist's aliases; the staff admin's approval is the backstop."""
    known = set(PLAIN_CAPITALISED)
    for text in (*(e.quote for e in sources), *(e.publisher for e in sources)):
        known.update(_WORD.findall(text))
    for org in allowlist.named():
        known.update(_WORD.findall(org.name))
        for alias in org.aliases:
            known.update(_WORD.findall(alias.text))
    found: list[str] = []
    for text in (title, summary):
        starts = _sentence_starts(text)
        for match in _CAPITALISED.finditer(text):
            token = match.group()
            ordinary = not any(c.isupper() or c.isdigit() for c in token[1:])
            if token in known or (match.start() in starts and ordinary):
                continue
            found.append(token)
    return tuple(dict.fromkeys(found))


def unsourced_names(names: Sequence[str], sources: Sequence[Excerpt], allowlist: Allowlist) -> tuple[str, ...]:
    """The names no cited source names itself: neither in its quote nor as its publisher, matched as the research
    agent matches a card (the allowlist's aliases, whole words, any case, any dash) or, for a name off the allowlist,
    as the name itself."""
    texts = [*(e.quote for e in sources), *(e.publisher for e in sources)]
    own = Allowlist(allowlist.country, (), tuple(Organisation(n, (Alias(n),)) for n in names))
    found = {n.casefold() for n in (*named_organisations(texts, (), allowlist), *named_organisations(texts, (), own))}
    return tuple(n for n in names if n.casefold() not in found)


def check_trend(
    draft: TrendDraft, sent: Mapping[str, Excerpt], allowlist: Allowlist, scoring: ResearchPolicy, as_of: date
) -> KeptTrend | Discarded:
    """Whether one drafted trend becomes a candidate (see the module docstring for the order of the checks).
    ``scoring`` is ``TrendsPolicy.scoring(research_policy)``."""
    title, summary = collapse(draft.title), collapse(draft.summary)
    declared = tuple(dict.fromkeys(n for n in (collapse(name) for name in draft.named_orgs) if n))
    reason = _text_reason(draft, title, summary, declared)
    if reason is not None:
        return Discarded(reason)
    topic = collapse(draft.topic_slug)
    if topic not in {e.topic_slug for e in sent.values()}:
        return Discarded(Reason.UNKNOWN_TOPIC)
    if len(draft.citations) < MIN_CITATIONS:
        return Discarded(Reason.NO_CITATION)
    if len(draft.citations) > MAX_CITATIONS:
        return Discarded(Reason.TOO_MANY_CITATIONS)
    if any(c.excerpt_id not in sent for c in draft.citations):
        return Discarded(Reason.UNKNOWN_EXCERPT)
    by_id: dict[str, Citation] = {}
    for citation in draft.citations:
        by_id.setdefault(citation.excerpt_id, citation)
    cited = tuple(
        CitedSource(sent[i], collapse(c.supporting_text)) for i, c in by_id.items() if verified(c, sent[i], scoring)
    )
    if not cited:
        return Discarded(Reason.NO_VERIFIED_CITATION)
    sources = tuple(c.excerpt for c in cited)
    if topic not in {e.topic_slug for e in sources}:
        return Discarded(Reason.TOPIC_NOT_CITED)
    if unquoted_hosts((title, summary), sources):
        return Discarded(Reason.LINK_IN_TEXT)
    names = named_organisations((title, summary), declared, allowlist)
    if len(names) > MAX_NAMED_ORGS:
        return Discarded(Reason.TEXT_OUT_OF_BOUNDS)
    violation = rule_violation(CardText(title, summary, "", names), sources)
    if violation is not None:
        return Discarded(Reason(violation))
    if unsourced_names(names, sources, allowlist) or unsourced_capitalised(title, summary, sources, allowlist):
        return Discarded(Reason.NAMED_ORG_WITHOUT_OFFICIAL)
    agreement = Decimal(len(cited)) / Decimal(len(by_id))
    score = confidence(sources, agreement, as_of, scoring)
    if score < scoring.discard_below:
        return Discarded(Reason.LOW_CONFIDENCE)
    return KeptTrend(title, summary, topic, names, cited, score, agreement)


def check_answer(
    answer: AnswerDraft,
    sent: Mapping[str, Excerpt],
    allowlist: Allowlist,
    scoring: ResearchPolicy,
    as_of: date,
    *,
    max_cards: int,
) -> AnswerVerdict:
    """The verdict on a whole answer (see the module docstring)."""
    if answer.injection_suspected:
        reasons = (Reason.INJECTION_SUSPECTED,) * len(answer.trends)
        return AnswerVerdict((), reasons, Reason.INJECTION_SUSPECTED)
    if not answer.trends:
        return AnswerVerdict((), (), Reason.NO_TRENDS)
    kept: list[KeptTrend] = []
    discarded: list[Reason] = []
    for draft in answer.trends[:max_cards]:
        verdict = check_trend(draft, sent, allowlist, scoring, as_of)
        if isinstance(verdict, Discarded):
            discarded.append(verdict.reason)
        else:
            kept.append(verdict)
    discarded += [Reason.OVER_CARD_LIMIT] * max(0, len(answer.trends) - max_cards)
    refused = None if kept else discarded[0]
    return AnswerVerdict(tuple(kept), tuple(discarded), refused)
