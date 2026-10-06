"""Scripted ``trend_synthesis`` answers for tests (D-18: no paid calls; AC-SEC-5: no network).

``valid_answer()`` is a fixed answer that passes every check for the week's excerpts: three trends written from the
saved excerpts tr-sec-001 (GitHub), tr-dat-002 (pgvector on postgresql.org) and tr-ke-002 (the Communications
Authority of Kenya), each number copied with the word that follows it in the quote and each organisation named by its
cited source. ``answer(variant)`` is one scripted answer per check of ``bridge.problems.trends.checks``
(``VARIANTS``): a variant named after a ``Reason`` is the first valid trend alone with that one fault, so the whole
answer is refused with that reason; ``"valid"``; ``"partly_valid"`` (the three trends, the second citing an invented
excerpt: two kept, one ``unknown_excerpt``); ``"over_card_limit"`` (four trends: three kept, one over the limit);
``"named_org_declared_only"`` (``named_org_without_official`` from ``named_orgs`` alone); ``"one_sentence"``
(``text_out_of_bounds`` from the summary's sentence count). ``FakeTrendsClient`` is the real ``LLMService`` over
``FakeAdapter`` (``bridge.llm.fakes.FakeLLMClient``) answering with those variants in order, so a test still goes
through the registry, the kill switch, the caps, the sanitiser and the ledger.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from bridge.llm.fakes import FakeLLMClient
from bridge.problems.trends.synthesis import TrendCitation, TrendOut, TrendSynthesis

VALID: Final = "valid"

SECURITY: Final = TrendOut(
    title="Unvalidated npm trusted publishing configurations now expire",
    summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation and can no longer"
    " authorize publishing. Developers in Kenya who publish npm packages should validate a new trusted publishing"
    " setup soon after creating it.",
    topic_slug="security",
    named_orgs=["GitHub"],
    citations=[TrendCitation(excerpt_ref="tr-sec-001", support="now expire 48 hours after creation")],
)
DATABASES: Final = TrendOut(
    title="pgvector 0.8.7 is now available with a buffer overflow fix",
    summary="pgvector 0.8.7 is now available. This release fixes a buffer overflow with IVFFlat index builds, which"
    " can lead to arbitrary code execution. Teams that use pgvector for search in their apps should plan the upgrade.",
    topic_slug="databases",
    named_orgs=[],
    citations=[
        TrendCitation(excerpt_ref="tr-dat-002", support="fixes a buffer overflow with IVFFlat index builds"),
    ],
)
KENYA: Final = TrendOut(
    title="New licence conditions published in the Kenya Gazette",
    summary="The new licence conditions were published in the Kenya Gazette on August 7, 2026. They take effect on"
    " September 7, following the statutory 30-day period. Developers in Kenya whose services fall under them should"
    " read the conditions.",
    topic_slug="kenya-ict",
    named_orgs=[],
    citations=[
        TrendCitation(
            excerpt_ref="tr-ke-002", support="will take effect on September 7, following the statutory 30-day period"
        )
    ],
)


def valid_answer() -> TrendSynthesis:
    return TrendSynthesis(injection_suspected=False, trends=[SECURITY, DATABASES, KENYA])


def _one(**changes: Any) -> TrendSynthesis:
    return TrendSynthesis(injection_suspected=False, trends=[SECURITY.model_copy(update=changes)])


def _cite(excerpt_ref: str, support: str) -> list[TrendCitation]:
    return [TrendCitation(excerpt_ref=excerpt_ref, support=support)]


VARIANTS: Final[dict[str, Callable[[], TrendSynthesis]]] = {
    VALID: valid_answer,
    "partly_valid": lambda: TrendSynthesis(
        injection_suspected=False,
        trends=[
            SECURITY,
            DATABASES.model_copy(update={"citations": _cite("tr-dat-999", "fixes a buffer overflow")}),
            KENYA,
        ],
    ),
    "over_card_limit": lambda: TrendSynthesis(injection_suspected=False, trends=[SECURITY, DATABASES, KENYA, SECURITY]),
    "injection_suspected": lambda: valid_answer().model_copy(update={"injection_suspected": True}),
    "no_trends": lambda: TrendSynthesis(injection_suspected=False, trends=[]),
    "control_character": lambda: _one(title="Unvalidated npm\u200b trusted publishing configurations now expire"),
    "non_latin_text": lambda: _one(title="Unvalidated npm trusted publishing c\u043enfigurations now expire"),
    "text_out_of_bounds": lambda: _one(title="Unvalidated npm trusted publishing configurations " * 3),
    "one_sentence": lambda: _one(summary="Unvalidated npm trusted publishing configurations now expire."),
    "unknown_topic": lambda: _one(topic_slug="blockchain"),
    "no_citation": lambda: _one(citations=[]),
    "too_many_citations": lambda: _one(citations=_cite("tr-sec-001", "now expire 48 hours after creation") * 6),
    "unknown_excerpt": lambda: _one(citations=_cite("tr-sec-999", "now expire 48 hours after creation")),
    "no_verified_citation": lambda: _one(citations=_cite("tr-sec-001", "expire two days after they are made")),
    "topic_not_cited": lambda: _one(topic_slug="web"),
    "unsupported_number": lambda: _one(
        summary="Unvalidated npm trusted publishing configurations now expire 72 hours after creation. Developers in"
        " Kenya who publish npm packages should validate them."
    ),
    "named_org_without_official": lambda: _one(
        summary="Unvalidated npm trusted publishing configurations now expire 48 hours after creation. Microsoft"
        " teams and developers in Kenya who publish npm packages should validate them."
    ),
    "named_org_declared_only": lambda: _one(named_orgs=["GitHub", "Microsoft"]),
}


def answer(variant: str = VALID) -> TrendSynthesis:
    return VARIANTS[variant]()


class FakeTrendsClient(FakeLLMClient):
    """``FakeLLMClient`` answering ``trend_synthesis`` with ``variants`` in order (``VARIANTS`` keys); other keyword
    arguments (``settings``, ``caps``, ...) go to ``FakeLLMClient``."""

    def __init__(self, *variants: str, **kwargs: Any) -> None:
        super().__init__([answer(variant) for variant in variants], **kwargs)
