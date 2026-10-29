"""AC-PROP-4 (REQ-PROP-04): two fixture proposals that differ only in Tier-2 fields produce byte-identical originality
responses across 50 submitted variations; no numeric score, Tier-2 text or other owner's teaser text appears.

The check runs end to end without a database: ``originality_explainer.run`` over an in-memory pool indexed exactly as
publish indexes (``submission_text`` of the whole record, Tier 2 included in the record), the fake embedder and the
real ``LLMService`` over a scripted adapter (``FakeLLMClient``), so the registry, the Tier-2 guard and the sanitiser
all run. Fakes only (D-18).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge.llm.demo_fallback import FallbackReason, fallback_result
from bridge.llm.errors import LLMProviderError, Tier2NotAllowed
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.types import CallContext, InputField, Message, Tier
from bridge.models.enums import OriginalityBand
from bridge.proposals import originality_explainer as ex
from bridge.proposals.originality import Assessment
from bridge.proposals.originality_explainer import OriginalityOut, OverlapExplanation
from bridge.proposals.originality_policy import load_originality_policy
from tests.unit.proposals.originality_fixtures import (
    COPY_ID,
    DRAFT_ID,
    OTHER,
    OWN_PUBLISHED_ID,
    SESSION,
    SUBMITTER,
    TEASER,
    THIRD,
    UNRELATED,
    UNRELATED_ID,
    InMemoryPool,
    Record,
    with_tier2,
)

POLICY = load_originality_policy()
CHECKED_AT = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
CANARY = "T2CANARY"
SENTENCE = "Both teasers are about keeping milk cold between farms and collection points."
TIER2_TEXT = st.text(st.characters(exclude_categories=["Cs"]), max_size=200)


def world(secret: str) -> tuple[InMemoryPool, dict[str, str]]:
    """The submitter's draft and the pool, every Tier-2 field carrying ``secret``; Tier 1 never changes."""
    pool = InMemoryPool(
        [
            Record(DRAFT_ID, SUBMITTER, with_tier2(TEASER, secret)),
            Record(OWN_PUBLISHED_ID, SUBMITTER, with_tier2(TEASER, secret)),
            Record(COPY_ID, OTHER, with_tier2(TEASER, secret)),
            Record(UNRELATED_ID, THIRD, with_tier2(UNRELATED, secret)),
        ]
    )
    return pool, with_tier2(TEASER, secret)


def sent(llm: FakeLLMClient) -> str:
    return "".join(
        block.text
        for request in llm.requests
        for part in (request.system, *(m.blocks for m in request.messages))
        for block in part
    )


async def check(secret: str) -> tuple[str, FakeLLMClient]:
    pool, draft = world(secret)
    llm = FakeLLMClient([OverlapExplanation(injection_suspected=False, sentence=SENTENCE)])
    out, _ = await ex.run(
        pool,
        pool.embedder,
        llm,
        draft,
        owner_id=SUBMITTER,
        proposal_id=DRAFT_ID,
        session_id=SESSION,
        policy=POLICY,
        checked_at=CHECKED_AT,
    )
    return out.model_dump_json(), llm


BASELINE, _ = asyncio.run(check(f"{CANARY} LoRa relays every 90 s, KES 25,000"))


@settings(max_examples=50, deadline=None)
@given(first=TIER2_TEXT, second=TIER2_TEXT)
def test_tier2_never_changes_the_response(first: str, second: str) -> None:
    """AC-PROP-4: 50 submitted variations; fixtures differing only in Tier 2 answer byte for byte the same."""
    a, llm_a = asyncio.run(check(CANARY + first))
    b, llm_b = asyncio.run(check(CANARY + second))
    assert a == b == BASELINE
    for llm in (llm_a, llm_b):
        assert len(llm.requests) == 1
        assert CANARY not in sent(llm)  # nothing confidential reached the model
        assert CANARY not in json.dumps([e.inputs for e in llm.ledger.entries], default=str)


def test_the_response_has_a_band_and_a_count_and_nothing_else() -> None:
    body = json.loads(BASELINE)
    assert body == {
        "demo_fallback": False,
        "band": "high_overlap",
        "compared": 2,  # the copy and the unrelated teaser; never the submitter's own
        "explanation": SENTENCE,
        "ai_drafted": True,
        "checked_at": "2026-10-02T09:30:00Z",
    }
    numbers = [v for v in body.values() if isinstance(v, int | float) and not isinstance(v, bool)]
    assert numbers == [2]
    assert CANARY not in BASELINE
    for teaser in (TEASER, UNRELATED):  # no other owner's teaser text
        assert not any(value in BASELINE for value in teaser.values())


async def test_tier2_text_never_matches_anyone() -> None:
    """Another owner's confidential field equal to the draft's teaser, and the draft's confidential field equal to
    another owner's teaser: neither is compared, so the band is none."""
    pool = InMemoryPool(
        [
            Record(UNRELATED_ID, THIRD, {**UNRELATED, "approach": " ".join(TEASER.values())}),
            Record(COPY_ID, OTHER, UNRELATED),
        ]
    )
    draft = {**TEASER, "notes": " ".join(UNRELATED.values())}
    llm = FakeLLMClient()
    out, why = await ex.run(
        pool,
        pool.embedder,
        llm,
        draft,
        owner_id=SUBMITTER,
        proposal_id=DRAFT_ID,
        session_id=SESSION,
        policy=POLICY,
        checked_at=CHECKED_AT,
    )
    assert (out.band, out.compared, out.explanation, why.reason) == (OriginalityBand.NONE, 2, None, "not_asked")
    assert llm.requests == []  # the explainer is never called for "none"


async def test_a_draft_against_an_empty_pool_is_none_with_zero_compared() -> None:
    pool = InMemoryPool([Record(OWN_PUBLISHED_ID, SUBMITTER, TEASER)])
    llm = FakeLLMClient()
    out, _ = await ex.run(
        pool,
        pool.embedder,
        llm,
        TEASER,
        owner_id=SUBMITTER,
        proposal_id=DRAFT_ID,
        session_id=SESSION,
        policy=POLICY,
        checked_at=CHECKED_AT,
    )
    assert (out.band, out.compared, out.explanation, llm.requests) == (OriginalityBand.NONE, 0, None, [])


# --- the explainer's inputs and what code accepts -------------------------------------------------------------------


def test_the_explainer_sees_tier1_fields_owned_by_their_authors() -> None:
    pool, draft = world(CANARY)
    teaser = pool._teaser(pool.records[2])
    [system, user] = ex.messages(SUBMITTER, draft, [teaser])
    assert not system.fields
    fields = {f.name: f for f in user.fields}
    assert all(f.tier is Tier.TIER1 and not f.public for f in fields.values())
    assert {n for n, f in fields.items() if f.owner_id == SUBMITTER} == {f"draft.{n}" for n in TEASER}
    assert {n for n, f in fields.items() if f.owner_id == OTHER} == {f"published.1.{n}" for n in TEASER}
    assert CANARY not in "".join(f.value for f in fields.values())


async def test_the_task_refuses_a_tier2_field() -> None:
    """``originality_explainer`` is Tier 1 only: the layer's guard refuses Tier 2 before anything is sent."""
    llm = FakeLLMClient()
    smuggled = [
        Message.system("x"),
        Message.user(InputField("confidential.approach", CANARY, tier=Tier.TIER2, owner_id=SUBMITTER)),
    ]
    with pytest.raises(Tier2NotAllowed):
        await llm.complete(ex.TASK, smuggled, OverlapExplanation, ctx=CallContext(user_id=SUBMITTER))
    assert llm.requests == []


@pytest.mark.parametrize(
    ("sentence", "reason"),
    [
        ("Both are about cold milk.", "explained"),
        ("", "empty"),
        ("They overlap by 92%.", "rejected:number"),
        ("Both describe how milk spoils before it reaches a cooler.", "rejected:copies_teaser"),
        ("Call 0712 345 678 to compare.", "rejected:number"),
        ("See coldchain.example.com for the other one.", "rejected:contact"),
        ("x" * 301, "rejected:too_long"),
    ],
)
def test_code_accepts_one_plain_sentence(sentence: str, reason: str) -> None:
    pool, _ = world(CANARY)
    got, why = ex.accept(sentence, [pool._teaser(pool.records[2])], POLICY)
    assert why == reason
    assert (got is None) == (reason != "explained")


async def test_a_demo_fallback_is_labelled_and_says_nothing() -> None:
    pool, draft = world(CANARY)

    class Fallback(FakeLLMClient):
        async def complete(self, *args: Any, **kwargs: Any) -> Any:
            return fallback_result(OverlapExplanation, reason=FallbackReason.NOT_DEMO_DATA, trace_id="t")

    out, why = await ex.run(
        pool,
        pool.embedder,
        Fallback(),
        draft,
        owner_id=SUBMITTER,
        proposal_id=DRAFT_ID,
        session_id=SESSION,
        policy=POLICY,
        checked_at=CHECKED_AT,
    )
    assert (out.band, out.demo_fallback, out.explanation, out.ai_drafted) == (
        OriginalityBand.HIGH_OVERLAP,
        True,
        None,
        False,
    )
    assert why.reason == "demo_fallback:not_demo_data"


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (OverlapExplanation(injection_suspected=True, sentence=SENTENCE), "injection_suspected"),
        (LLMProviderError("down", transient=True), "llm_error:llm_provider"),
    ],
)
async def test_no_sentence_when_the_model_is_steered_or_down(reply: object, reason: str) -> None:
    llm = FakeLLMClient([reply])  # type: ignore[list-item]
    assessment = Assessment(OriginalityBand.SOME_OVERLAP, 1, (world(CANARY)[0]._teaser(world(CANARY)[0].records[2]),))
    got = await ex.explain(llm, assessment, TEASER, owner_id=SUBMITTER, session_id=SESSION, policy=POLICY)
    assert (got.sentence, got.reason) == (None, reason)


def test_the_placeholder_is_the_safe_answer() -> None:
    assert OverlapExplanation.demo_fallback().injection_suspected is True
    assert set(OriginalityOut.model_fields) == {
        "demo_fallback",
        "band",
        "compared",
        "explanation",
        "ai_drafted",
        "checked_at",
    }
