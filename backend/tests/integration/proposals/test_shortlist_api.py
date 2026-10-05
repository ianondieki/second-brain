"""REQ-REPO-02 (R10), P21 track B, D-57 (5) and (6): the organisation shortlist and side-by-side compare, through the
API as ``bridge_app`` (revision 0008's ``org_shortlist`` and ``app_org_sees_proposal``).

- P21-B1: a member with a Tier-2 role (reviewer, signatory, admin) adds and removes; every member (a viewer too)
  reads the list, each entry saying who added it and when; a viewer or finance member cannot add or remove (403).
- P21-B2: another organisation neither reads nor adds to it (404), and nothing of it shows on its own list.
- P21-B3: a proposal the organisation cannot see in its Inbox (not pitched to it, not matched by its scout, not
  answering its Brief; or no proposal at all) cannot be added (404).
- P21-B4: compare takes 2 to 4 distinct shortlisted proposals (else 422) and answers Tier-1 facts only: no Tier-2 field
  name and no Tier-2 text anywhere in the payload, even for a proposal whose Tier 2 the organisation was granted.
- P21-B5: adding and removing write audit events (``shortlist.added``, ``shortlist.removed``), once each.
- P21-B6: the Inbox's "sent to you" rows and the scout matches carry ``shortlisted`` for each proposal.
- Every read asks again whether the organisation still sees each proposal (the 0008 security review): one held by
  moderation after it was shortlisted shows on the list as unavailable with no Tier-1 facts, can still be removed, and
  is left out of compare; one whose tag was withdrawn (no longer in the Inbox) likewise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.seed.reference import load_reference, seed_regions
from tests.integration import world as w
from tests.integration.proposals.helpers import TIER2_MARKERS, Developers, ProposalWorld, rows
from tests.integration.proposals.pitch_helpers import Members, Org, PitchOrgs, add_member, pitch, pitchable

ENTRY_KEYS = {"proposal_id", "available", "title", "niche", "added_by_id", "added_by_name", "added_at"}
COMPARE_KEYS = {
    "proposal_id",
    "title",
    "niche",
    "country",
    "county_code",
    "maturity",
    "ask",
    "cert_id",
    "registered_at",
    "engagement",
    "fit_score",
}
# docs/spec/06 6.1 Tier 2 (and what a Tier-2 render carries): none of these may be a key of the compare payload.
TIER2_FIELDS = {"approach", "architecture", "pricing", "notes", "links", "attachments", "confidential"}


@dataclass(frozen=True, slots=True)
class Scene:
    org: Org
    reviewer: UUID
    viewer: UUID
    finance: UUID
    signatory: UUID
    pitched: list[str]  # three proposals pitched to the organisation (delivered tags: each opened an engagement)
    matched: str  # published, matched by the organisation's scout, never pitched
    unseen: str  # published, in none of the organisation's Inbox lists


def shortlist_url(org: Org | UUID, proposal: str | UUID | None = None) -> str:
    org_id = org.id if isinstance(org, Org) else org
    base = f"/api/orgs/{org_id}/shortlist"
    return base if proposal is None else f"{base}/{proposal}"


async def scene(
    developers: Developers, world: ProposalWorld, orgs: PitchOrgs, owner_engine: AsyncEngine, *, pitched: int = 3
) -> Scene:
    org = orgs.safaricom
    assert org.member is not None
    async with owner_engine.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])  # the counties a teaser may name (idempotent)
        viewer = await add_member(conn, org.id, "{viewer}")
        finance = await add_member(conn, org.id, "{finance}")
        signatory = await add_member(conn, org.id, "{signatory}")
    sent: list[str] = []
    for n in range(pitched):
        dev, proposal_id = await pitchable(developers, world, title=f"Shortlist idea {n}", county_code="KE-30")
        assert (await pitch(dev, proposal_id, org)).status_code == 201
        sent.append(proposal_id)
    _, matched = await pitchable(developers, world, title="Matched idea")
    _, unseen = await pitchable(developers, world, title="Unseen idea")
    async with owner_engine.begin() as conn:
        version = (
            await conn.execute(text("SELECT current_version_id FROM proposals WHERE id = :p"), {"p": matched})
        ).scalar_one()
        owner = await add_member(conn, org.id, "{owner,admin}")
        await w.add_scout_rows(conn, org.id, owner, world.niche_id, UUID(matched), version)
    return Scene(org, org.member, viewer, finance, signatory, sent, matched, unseen)


async def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


async def audit_count(owner_engine: AsyncEngine, org: UUID, action: str, proposal: str) -> int:
    found = await rows(
        owner_engine,
        "SELECT count(*) FROM audit_events WHERE org_id = :org AND action = :action AND subject_id = :p",
        org=org,
        action=action,
        p=UUID(proposal),
    )
    return int(found[0][0])


async def test_p21_b1_tier2_members_add_and_remove_and_every_member_reads(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=2)
    reviewer, signatory = await member_client(s.reviewer), await member_client(s.signatory)
    viewer, finance = await member_client(s.viewer), await member_client(s.finance)
    first, second = s.pitched

    assert await ok(await viewer.get(shortlist_url(s.org))) == {"items": [], "next_cursor": None}
    added = await ok(await reviewer.put(shortlist_url(s.org, first)))
    assert set(added) == ENTRY_KEYS
    assert (added["proposal_id"], added["available"], added["title"]) == (first, True, "Shortlist idea 0")
    assert added["niche"]["label"] == proposal_world.niche_label
    assert (added["added_by_id"], added["added_by_name"]) == (str(s.reviewer), "Member")
    again = await ok(await signatory.put(shortlist_url(s.org, first)))  # idempotent: the first add stays
    assert again == added
    await ok(await signatory.put(shortlist_url(s.org, s.matched)))

    for member in (viewer, finance, reviewer, signatory):
        listed = await ok(await member.get(shortlist_url(s.org)))
        assert [item["proposal_id"] for item in listed["items"]] == [s.matched, first]  # newest first
        assert all(set(item) == ENTRY_KEYS for item in listed["items"])
    paged = await ok(await viewer.get(shortlist_url(s.org), params={"limit": 1}))
    assert [item["proposal_id"] for item in paged["items"]] == [s.matched]
    rest = await ok(await viewer.get(shortlist_url(s.org), params={"limit": 1, "cursor": paged["next_cursor"]}))
    assert ([item["proposal_id"] for item in rest["items"]], rest["next_cursor"]) == ([first], None)
    assert code(await viewer.get(shortlist_url(s.org), params={"cursor": "nope"})) == (400, "invalid_cursor")

    for member in (viewer, finance):
        assert code(await member.put(shortlist_url(s.org, second))) == (403, "forbidden")
        assert code(await member.delete(shortlist_url(s.org, first))) == (403, "forbidden")
    assert await ok(await reviewer.delete(shortlist_url(s.org, first)), 204) is None
    assert await ok(await reviewer.delete(shortlist_url(s.org, first)), 204) is None  # removing again changes nothing
    listed = await ok(await viewer.get(shortlist_url(s.org)))
    assert [item["proposal_id"] for item in listed["items"]] == [s.matched]


async def test_p21_b2_another_organisation_neither_reads_nor_adds(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=1)
    [pitched] = s.pitched
    reviewer = await member_client(s.reviewer)
    await ok(await reviewer.put(shortlist_url(s.org, pitched)))
    outsider = await member_client(pitch_orgs.airtel.member)  # type: ignore[arg-type]
    for response in (
        await outsider.get(shortlist_url(s.org)),
        await outsider.put(shortlist_url(s.org, pitched)),
        await outsider.delete(shortlist_url(s.org, pitched)),
        await outsider.get(f"{shortlist_url(s.org)}/compare", params={"ids": f"{pitched},{s.matched}"}),
    ):
        assert code(response) == (404, "not_found")
    # Its own shortlist: the other organisation's Inbox proposal is not in its Inbox (404) and nothing leaks into it.
    assert code(await outsider.put(shortlist_url(pitch_orgs.airtel, pitched))) == (404, "not_found")
    assert await ok(await outsider.get(shortlist_url(pitch_orgs.airtel))) == {"items": [], "next_cursor": None}
    developer = await developers()
    assert code(await developer.get(shortlist_url(s.org))) == (404, "not_found")
    listed = await ok(await reviewer.get(shortlist_url(s.org)))
    assert [item["proposal_id"] for item in listed["items"]] == [pitched]  # the outsider's DELETE removed nothing


async def test_p21_b3_only_a_proposal_of_the_inbox_can_be_added(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=1)
    reviewer = await member_client(s.reviewer)
    for proposal in (s.unseen, str(uuid4())):
        assert code(await reviewer.put(shortlist_url(s.org, proposal))) == (404, "not_found")
    assert (await reviewer.put(shortlist_url(s.org, "not-a-uuid"))).status_code == 422
    await ok(await reviewer.put(shortlist_url(s.org, s.matched)))  # matched by its scout: in the Inbox
    await ok(await reviewer.put(shortlist_url(s.org, s.pitched[0])))  # pitched to it
    listed = await ok(await reviewer.get(shortlist_url(s.org)))
    assert {item["proposal_id"] for item in listed["items"]} == {s.matched, s.pitched[0]}


def keys_of(value: Any) -> set[str]:
    """Every key of every object in a JSON document."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys_of(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys_of(item)}
    return set()


async def test_p21_b4_compare_two_to_four_shortlisted_on_tier1_facts_only(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=4)
    reviewer, viewer = await member_client(s.reviewer), await member_client(s.viewer)
    shortlisted = [*s.pitched, s.matched]
    for proposal in shortlisted:
        await ok(await reviewer.put(shortlist_url(s.org, proposal)))
    url = f"{shortlist_url(s.org)}/compare"

    def ids(*proposals: str) -> dict[str, str]:
        return {"ids": ",".join(proposals)}

    refused = {
        "one": ids(shortlisted[0]),
        "five": ids(*shortlisted),
        "repeated": ids(shortlisted[0], shortlisted[0]),
        "not shortlisted": ids(shortlisted[0], s.unseen),
        "unknown": ids(shortlisted[0], str(uuid4())),
        "malformed": ids(shortlisted[0], "nope"),
        "empty": {"ids": ""},
    }
    for why, params in refused.items():
        response = await viewer.get(url, params=params)
        assert response.status_code == 422, (why, response.text)
    assert (await viewer.get(url)).status_code == 422  # no ids at all

    for chosen in (shortlisted[:2], shortlisted[1:4], [s.matched, *s.pitched[:3]]):
        body = await ok(await viewer.get(url, params=ids(*chosen)))
        assert set(body) == {"items"}
        assert [item["proposal_id"] for item in body["items"]] == chosen  # in the order asked
    body = await ok(await viewer.get(url, params=ids(s.pitched[0], s.matched)))
    pitched, matched = body["items"]
    for item in (pitched, matched):
        assert set(item) == COMPARE_KEYS
        assert (item["maturity"], item["ask"], item["country"]) == ("prototype", "pilot", "KE")
        assert item["niche"]["label"] == proposal_world.niche_label
        assert item["cert_id"]
        assert item["registered_at"]
    assert (pitched["title"], pitched["county_code"]) == ("Shortlist idea 0", "KE-30")
    assert set(pitched["engagement"]) == {"id", "state"}
    assert pitched["engagement"]["state"] == "SUBMITTED"  # the pitch opened it
    assert pitched["fit_score"] is None  # not matched by a scout
    assert (matched["title"], matched["engagement"], matched["fit_score"]) == ("Matched idea", None, 70)

    # Tier 1 only: the pitched proposals' Tier 2 was granted to the organisation (an E2 pitch), and still no Tier-2
    # field name or text reaches compare.
    granted = await rows(
        owner_engine,
        "SELECT count(*) FROM disclosure_grants WHERE org_id = :org AND proposal_id = :p AND status = 'active'",
        org=s.org.id,
        p=UUID(s.pitched[0]),
    )
    assert granted[0][0] >= 1
    everything = await ok(await viewer.get(url, params=ids(*shortlisted[:4])))
    assert not keys_of(everything) & TIER2_FIELDS
    payload = json.dumps(everything)
    assert not any(marker in payload for marker in TIER2_MARKERS)


async def test_p21_b5_adding_and_removing_are_audited_once_each(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=1)
    [proposal] = s.pitched
    reviewer = await member_client(s.reviewer)
    await ok(await reviewer.put(shortlist_url(s.org, proposal)))
    await ok(await reviewer.put(shortlist_url(s.org, proposal)))  # a repeat adds nothing, so no second event
    assert await audit_count(owner_engine, s.org.id, "shortlist.added", proposal) == 1
    assert await audit_count(owner_engine, s.org.id, "shortlist.removed", proposal) == 0
    await ok(await reviewer.delete(shortlist_url(s.org, proposal)), 204)
    await ok(await reviewer.delete(shortlist_url(s.org, proposal)), 204)  # nothing left to remove: no event
    assert await audit_count(owner_engine, s.org.id, "shortlist.removed", proposal) == 1
    [event] = await rows(
        owner_engine,
        "SELECT actor_user_id, subject_type, payload FROM audit_events WHERE org_id = :org AND action = :a"
        " AND subject_id = :p",
        org=s.org.id,
        a="shortlist.removed",
        p=UUID(proposal),
    )
    assert (event.actor_user_id, event.subject_type, event.payload) == (s.reviewer, "proposal", {})


async def test_p21_b6_the_inbox_and_the_scout_matches_show_the_star(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=2)
    reviewer, viewer = await member_client(s.reviewer), await member_client(s.viewer)
    starred, plain = s.pitched
    await ok(await reviewer.put(shortlist_url(s.org, starred)))
    await ok(await reviewer.put(shortlist_url(s.org, s.matched)))

    inbox = await ok(await viewer.get(f"/api/orgs/{s.org.id}/inbox"))
    assert {item["proposal"]["id"]: item["shortlisted"] for item in inbox["items"]} == {starred: True, plain: False}
    matches = await ok(await viewer.get(f"/api/orgs/{s.org.id}/matches"))
    assert [(item["proposal_id"], item["shortlisted"]) for item in matches["items"]] == [(s.matched, True)]
    [match] = matches["items"]
    detail = await ok(await viewer.get(f"/api/orgs/{s.org.id}/matches/{match['id']}"))
    assert detail["shortlisted"] is True

    await ok(await reviewer.delete(shortlist_url(s.org, s.matched)), 204)
    matches = await ok(await viewer.get(f"/api/orgs/{s.org.id}/matches"))
    assert [item["shortlisted"] for item in matches["items"]] == [False]
    # Another organisation's star never shows: the airtel member pitched nothing and sees nothing starred.
    other = await member_client(pitch_orgs.airtel.member)  # type: ignore[arg-type]
    assert (await ok(await other.get(f"/api/orgs/{pitch_orgs.airtel.id}/inbox")))["items"] == []


async def test_a_proposal_the_organisation_no_longer_sees_is_unavailable_and_left_out_of_compare(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=3)
    reviewer, viewer = await member_client(s.reviewer), await member_client(s.viewer)
    held, gone, kept = s.pitched
    for proposal in (*s.pitched, s.matched):
        await ok(await reviewer.put(shortlist_url(s.org, proposal)))
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE proposals SET moderation_state = 'held' WHERE id = :p"), {"p": UUID(held)})
        await conn.execute(  # the tag withdrawn: no longer pitched to the organisation, so out of its Inbox
            text("UPDATE tags SET status = 'withdrawn', closed_at = now() WHERE proposal_id = :p AND org_id = :org"),
            {"p": UUID(gone), "org": s.org.id},
        )

    listed = await ok(await viewer.get(shortlist_url(s.org)))
    by_id = {item["proposal_id"]: item for item in listed["items"]}
    assert set(by_id) == {held, gone, kept, s.matched}  # the rows stay: a working list a Tier-2 member tidies
    for proposal in (held, gone):
        item = by_id[proposal]
        assert (item["available"], item["title"], item["niche"]) == (False, None, None)
        assert item["added_by_id"] == str(s.reviewer)
    assert (by_id[kept]["available"], by_id[kept]["title"]) == (True, "Shortlist idea 2")
    assert code(await reviewer.put(shortlist_url(s.org, held))) == (404, "not_found")  # cannot be re-added now

    body = await ok(await viewer.get(f"{shortlist_url(s.org)}/compare", params={"ids": f"{held},{kept},{gone}"}))
    assert [item["proposal_id"] for item in body["items"]] == [kept]
    assert "Shortlist idea 0" not in json.dumps(body)  # the held proposal's title

    await ok(await reviewer.delete(shortlist_url(s.org, held)), 204)
    listed = await ok(await viewer.get(shortlist_url(s.org)))
    assert held not in {item["proposal_id"] for item in listed["items"]}


async def test_a_proposal_whose_author_joins_the_organisation_leaves_the_shortlist_view(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    member_client: Members,
    owner_engine: AsyncEngine,
) -> None:
    """P10's rule (as the scout matches): a member's own proposal is never shown to their organisation, so the
    shortlist never tells who wrote it. Once the author is an active member, the entry is unavailable with no facts,
    compare leaves it out and it cannot be added again (404); the matches view agrees."""
    s = await scene(developers, proposal_world, pitch_orgs, owner_engine, pitched=2)
    reviewer = await member_client(s.reviewer)
    joined, kept = s.pitched
    for proposal in (joined, kept, s.matched):
        await ok(await reviewer.put(shortlist_url(s.org, proposal)))
    async with owner_engine.begin() as conn:
        for proposal in (joined, s.matched):  # each author joins the organisation as an active member
            await conn.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles) SELECT :id, :org, owner_id,"
                    " CAST('{viewer}' AS org_role[]) FROM proposals WHERE id = :p"
                ),
                {"id": uuid4(), "org": s.org.id, "p": UUID(proposal)},
            )

    listed = await ok(await reviewer.get(shortlist_url(s.org)))
    by_id = {item["proposal_id"]: item for item in listed["items"]}
    for proposal in (joined, s.matched):
        assert (by_id[proposal]["available"], by_id[proposal]["title"], by_id[proposal]["niche"]) == (False, None, None)
    assert by_id[kept]["available"] is True
    assert code(await reviewer.put(shortlist_url(s.org, joined))) == (404, "not_found")
    body = await ok(await reviewer.get(f"{shortlist_url(s.org)}/compare", params={"ids": f"{joined},{kept}"}))
    assert [item["proposal_id"] for item in body["items"]] == [kept]
    [match] = (await ok(await reviewer.get(f"/api/orgs/{s.org.id}/matches")))["items"]
    assert (match["proposal_id"], match["available"]) == (s.matched, False)  # the same answer as the matches view
    await ok(await reviewer.delete(shortlist_url(s.org, joined)), 204)  # still removable
