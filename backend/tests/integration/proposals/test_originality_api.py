"""REQ-PROP-04 through the API: the originality check of a draft against other owners' published teasers.

Publish writes the 16 LSH bands and the teaser embedding (the fake embedder). A check is owner only (404 for anyone
else's proposal, published or not: AC-SEC-1/b), counts one ``originality_checks`` row per call with its audit event in
the same commit, and answers 429 ``originality_limit`` on the 11th of a Nairobi day. With the fake provider an overlap
is labelled "demo fallback" with no sentence; the explainer is never called for the band ``none``; with a free
provider and demo accounts it is, on Tier-1 text only. The pool is other owners' published, clear teasers only.
Nothing in a response carries a score, Tier-2 text or another owner's text.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import clock
from bridge.llm.embeddings import FAKE_MODEL, FakeEmbedder, vector_with_similarity
from bridge.llm.errors import LLMConfigError
from bridge.proposals import originality, originality_explainer
from bridge.proposals.assistant import InFlight
from bridge.proposals.originality_explainer import OverlapExplanation
from tests.integration.proposals.assistant_rig import audit_rows, install, llm_rows, make_demo, new_draft
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    published,
    rows,
    user_of,
)

PATH = "/api/me/proposals/{}/originality"
SENTENCE = "Both teasers are about keeping water flowing to villages when pumps fail."


def coined(tag: str, index: int) -> str:
    """A made-up six-letter word, the same for the same tag and index."""
    digest = hashlib.sha256(f"{tag}:{index}".encode()).digest()
    return "".join("bdfgklmnprstvz"[digest[i] % 14] + "aeiou"[digest[i + 1] % 5] for i in (0, 2, 4))


def unique_teaser(tag: str) -> dict[str, Any]:
    """A teaser whose words, stop words aside, are coined from ``tag``: two tags share no token and no shingle, so the
    fake embedder's bag-of-words vectors of two of them are near-orthogonal (REQ-EMB-01) and only the same tag
    overlaps, whatever the other tests have published."""
    w = [coined(tag, i) for i in range(21)]
    return {
        "title": f"{w[0].title()} {w[1]} for {tag}",
        "problem_statement": f"The {w[2]} {w[3]} in {tag} {w[4]} and the {w[5]} {w[6]} for {w[7]} at a {w[8]}.",
        "impact_claims": f"{w[9].title()} {w[10]} for {tag} {w[11]}.",
        "summary": f"The {w[12]} {w[13]} in {tag} {w[14]} a {w[15]} when a {w[16]} {w[17]},"
        f" so {w[18]} {w[19]} {w[20]}.",
    }


async def check(client: httpx.AsyncClient, proposal_id: object) -> httpx.Response:
    return await client.post(PATH.format(proposal_id))


async def count_checks(engine: AsyncEngine, user_id: UUID) -> int:
    [row] = await rows(engine, "SELECT count(*) AS n FROM originality_checks WHERE user_id = :u", u=user_id)
    return int(row.n)


def assert_no_leak(body: dict[str, Any], *others: dict[str, Any]) -> None:
    raw = json.dumps(body)
    assert set(body) == {"demo_fallback", "band", "compared", "explanation", "ai_drafted", "checked_at"}
    assert not any(marker in raw for marker in TIER2_MARKERS)
    for teaser in others:
        assert not any(value in raw for value in teaser.values())
    assert isinstance(body["compared"], int)
    assert body["explanation"] is None or not any(ch.isdigit() for ch in body["explanation"])


async def test_publish_indexes_the_tier1_teaser(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    install(client, provider="fake")
    out = await published(client, proposal_world, **unique_teaser(proposal_world.tag + "ix"))
    bands = await rows(owner_engine, "SELECT band FROM proposal_lsh_bands WHERE proposal_id = :p", p=out["proposal_id"])
    assert sorted(r.band for r in bands) == list(range(originality.BANDS))
    [row] = await rows(
        owner_engine,
        "SELECT teaser_embedding IS NOT NULL AS has_vector, embed_model FROM proposals WHERE id = :p",
        p=out["proposal_id"],
    )
    assert (row.has_vector, row.embed_model) == (True, FAKE_MODEL)


async def test_owner_only(developers: Developers, proposal_world: ProposalWorld) -> None:
    owner, stranger = await developers(), await developers()
    for client in (owner, stranger):
        install(client, provider="fake")
    out = await published(owner, proposal_world, **unique_teaser(proposal_world.tag + "own"))
    draft = await create(owner, draft_body(proposal_world))
    refused = await check(stranger, out["proposal_id"])
    assert refused.status_code == 404, refused.text  # a published teaser is visible, yet not theirs to check
    assert refused.json()["detail"]["code"] == "not_found"
    assert (await stranger.get(PATH.format(out["proposal_id"]))).status_code == 404
    assert (await check(stranger, draft["id"])).status_code == 404
    assert (await check(owner, "01900000-0000-7000-8000-00000000dead")).status_code == 404
    assert (await check(owner, out["proposal_id"])).status_code == 200  # the owner checks a published one too


async def test_an_overlap_with_the_fake_provider_is_labelled_and_kept_for_the_day(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    author, submitter = await developers(), await developers()
    teaser = unique_teaser(proposal_world.tag + "fb")
    install(author, provider="fake")
    await published(author, proposal_world, **teaser)
    install(submitter, provider="fake")
    proposal_id = await new_draft(submitter, proposal_world, **teaser)
    assert (await submitter.get(PATH.format(proposal_id))).json() is None  # nothing checked yet today

    response = await check(submitter, proposal_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["band"], body["demo_fallback"], body["explanation"], body["ai_drafted"]) == (
        "high_overlap",
        True,
        None,
        False,
    )
    assert body["compared"] >= 1
    assert_no_leak(body, teaser)
    assert await count_checks(owner_engine, user_of(submitter)) == 1
    assert await llm_rows(owner_engine, user_of(submitter)) == []  # the fallback writes no ledger row
    assert (await submitter.get(PATH.format(proposal_id))).json() == body


async def test_the_explainer_is_never_called_for_none(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    await make_demo(owner_engine, user_of(client))
    adapter = install(client)  # a free slot with no scripted reply: a call would fail loudly
    proposal_id = await new_draft(client, proposal_world, **unique_teaser(proposal_world.tag + "none"))
    response = await check(client, proposal_id)
    assert response.status_code == 200, response.text
    assert (response.json()["band"], response.json()["explanation"]) == ("none", None)
    assert adapter.requests == []
    assert await llm_rows(owner_engine, user_of(client)) == []


async def test_demo_accounts_get_a_checked_sentence_from_tier1_only(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    author, submitter = await developers(), await developers()
    for client in (author, submitter):
        await make_demo(owner_engine, user_of(client))
    teaser = unique_teaser(proposal_world.tag + "demo")
    install(author, provider="fake")
    await published(author, proposal_world, **teaser)
    adapter = install(submitter, OverlapExplanation(injection_suspected=False, sentence=SENTENCE))
    proposal_id = await new_draft(submitter, proposal_world, **teaser)

    body = (await check(submitter, proposal_id)).json()
    assert (body["band"], body["explanation"], body["ai_drafted"], body["demo_fallback"]) == (
        "high_overlap",
        SENTENCE,
        True,
        False,
    )
    assert_no_leak(body, teaser)
    [request] = adapter.requests
    sent = "".join(b.text for m in request.messages for b in m.blocks)
    assert teaser["summary"] in sent  # the submitter's and the matched teaser's Tier 1 ...
    assert not any(marker in sent for marker in TIER2_MARKERS)  # ... and nothing confidential
    [ledger] = await llm_rows(owner_engine, user_of(submitter))
    assert (ledger.status, ledger.purpose) == ("ok", None)  # no consent purpose: Tier 1 only
    assert (await submitter.get(PATH.format(proposal_id))).json()["explanation"] == SENTENCE


async def test_ten_checks_a_day_then_429(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    install(client, provider="fake")
    proposal_id = await new_draft(client, proposal_world, **unique_teaser(proposal_world.tag + "lim"))
    for _ in range(10):
        assert (await check(client, proposal_id)).status_code == 200
    refused = await check(client, proposal_id)
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == {"code": "originality_limit", "message": originality.LIMIT}
    assert await count_checks(owner_engine, user_of(client)) == 10  # one row per check, none for the refusal
    [row] = await rows(
        owner_engine,
        "SELECT count(DISTINCT band) AS n FROM originality_checks WHERE user_id = :u AND band = 'none'",
        u=user_of(client),
    )
    assert row.n == 1  # the band is kept, nothing else

    other = await developers()  # the limit is per developer
    install(other, provider="fake")
    theirs = await new_draft(other, proposal_world)
    assert (await check(other, theirs)).status_code == 200


async def test_a_running_check_answers_busy_and_a_new_day_starts_afresh(
    developers: Developers, proposal_world: ProposalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = await developers()
    install(client, provider="fake")
    proposal_id = await new_draft(client, proposal_world, **unique_teaser(proposal_world.tag + "busy"))
    running = InFlight()
    client.app.state.originality_in_flight = running  # type: ignore[attr-defined]
    assert running.claim(UUID(proposal_id), 1)
    busy = await check(client, proposal_id)
    assert (busy.status_code, busy.json()["detail"]["code"]) == (429, "originality_busy")
    running.release(UUID(proposal_id))

    assert (await check(client, proposal_id)).status_code == 200
    assert (await client.get(PATH.format(proposal_id))).json() is not None
    turned = clock.utcnow() + timedelta(minutes=1)  # the Nairobi day turns (the session would not survive a real day)
    monkeypatch.setattr(originality, "nairobi_day_start", lambda now: turned)
    assert (await client.get(PATH.format(proposal_id))).json() is None  # only today's check is shown again


async def test_a_near_copy_is_found_through_the_stored_buckets(
    developers: Developers, proposal_world: ProposalWorld
) -> None:
    """The submitter's embedder is pinned to put the two texts far apart (the bag-of-words fake would put them close),
    so only the LSH buckets in the database can find the copy."""
    author, submitter = await developers(), await developers()
    teaser = unique_teaser("Lodwar")  # fixed text: the bucket overlap below is a fact, not a chance
    near = {**teaser, "summary": " ".join([*teaser["summary"].split()[:-1], "sooner."])}
    theirs, mine = (originality.shingles(originality.submission_text(t)) for t in (teaser, near))
    assert 0.8 <= originality.jaccard(theirs, mine) < 1.0
    assert set(originality.lsh_bands(originality.signature(theirs))) & set(
        originality.lsh_bands(originality.signature(mine))
    )
    install(author, provider="fake")
    await published(author, proposal_world, **teaser)
    install(submitter, provider="fake")
    published_vector = FakeEmbedder().vector_for(originality.submission_text(teaser))
    apart = vector_with_similarity(published_vector, 0.0)
    submitter.app.state.embedder = FakeEmbedder({originality.submission_text(near): apart})  # type: ignore[attr-defined]
    proposal_id = await new_draft(submitter, proposal_world, **near)
    body = (await check(submitter, proposal_id)).json()
    assert body["band"] == "high_overlap"
    assert_no_leak(body, teaser)


async def test_the_last_check_is_shown_only_for_the_text_it_was_about(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    client = await developers()
    install(client, provider="fake")
    teaser = unique_teaser(proposal_world.tag + "txt")
    proposal_id = await new_draft(client, proposal_world, **teaser)
    body = (await check(client, proposal_id)).json()
    [payload] = await audit_rows(owner_engine, user_of(client), "proposal.originality_checked")
    assert payload["text_sha256"] == originality.text_digest(teaser)
    assert (await client.get(PATH.format(proposal_id))).json() == body

    url = f"/api/me/proposals/{proposal_id}"
    assert (await client.patch(url, json={"teaser": {"summary": "Something else entirely."}})).status_code == 200
    assert (await client.get(PATH.format(proposal_id))).json() is None  # the band was about other text
    assert (await client.patch(url, json={"teaser": {"summary": teaser["summary"]}})).status_code == 200
    assert (await client.get(PATH.format(proposal_id))).json() == body  # the same text again
    assert (await client.patch(url, json={"confidential": {"notes": "changed"}})).status_code == 200
    assert (await client.get(PATH.format(proposal_id))).json() == body  # Tier 2 is not part of the check


async def test_a_failure_after_the_count_still_leaves_its_audit_event(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A code mistake in the explainer step: the check was counted, and its record was committed with the count."""

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise LLMConfigError("a code mistake after the count")

    monkeypatch.setattr(originality_explainer, "explain", broken)
    client = await developers()
    install(client, provider="fake")
    proposal_id = await new_draft(client, proposal_world, **unique_teaser(proposal_world.tag + "err"))
    try:
        response = await check(client, proposal_id)
        assert response.status_code == 500
    except LLMConfigError:
        pass  # the transport re-raises the app's unhandled error
    assert await count_checks(owner_engine, user_of(client)) == 1
    [payload] = await audit_rows(owner_engine, user_of(client), "proposal.originality_checked")
    assert (payload["band"], payload["compared"] >= 0) == ("none", True)


async def test_the_owners_own_published_teaser_never_counts(
    developers: Developers, proposal_world: ProposalWorld
) -> None:
    owner = await developers()
    install(owner, provider="fake")
    teaser = unique_teaser(proposal_world.tag + "self")
    copy = await new_draft(owner, proposal_world, **teaser)
    before = (await check(owner, copy)).json()
    await published(owner, proposal_world, **teaser)  # the same text, published by the same owner
    after = (await check(owner, copy)).json()
    assert (after["band"], after["compared"]) == ("none", before["compared"])


async def test_held_and_hidden_teasers_are_outside_the_pool(
    developers: Developers, proposal_world: ProposalWorld
) -> None:
    author, submitter = await developers(), await developers()
    for client in (author, submitter):
        install(client, provider="fake")
    held = unique_teaser(proposal_world.tag + "held") | {"title": f"Why {proposal_world.org_brand} overcharges"}
    hidden = unique_teaser(proposal_world.tag + "hid")
    mine_held = await new_draft(submitter, proposal_world, **held)
    mine_hidden = await new_draft(submitter, proposal_world, **hidden)
    baseline = (await check(submitter, mine_held)).json()["compared"]

    out = await published(author, proposal_world, **held)
    assert out["moderation"]["state"] == "held"  # the pre-screen holds it
    gone = await published(author, proposal_world, **hidden)
    assert (await author.delete(f"/api/me/proposals/{gone['proposal_id']}")).status_code == 200
    for proposal_id in (mine_held, mine_hidden):
        body = (await check(submitter, proposal_id)).json()
        assert (body["band"], body["compared"]) == ("none", baseline)


async def test_a_non_demo_author_keeps_the_free_provider_out(
    developers: Developers, owner_engine: AsyncEngine, proposal_world: ProposalWorld
) -> None:
    """D-37: the submitter is a demo account, the matched author is not: nothing goes to the free provider."""
    author, submitter = await developers(), await developers()
    await make_demo(owner_engine, user_of(submitter))
    teaser = unique_teaser(proposal_world.tag + "d37")
    install(author, provider="fake")
    await published(author, proposal_world, **teaser)
    adapter = install(submitter, OverlapExplanation(injection_suspected=False, sentence=SENTENCE))
    proposal_id = await new_draft(submitter, proposal_world, **teaser)
    body = (await check(submitter, proposal_id)).json()
    assert (body["band"], body["demo_fallback"], body["explanation"]) == ("high_overlap", True, None)
    assert adapter.requests == []
