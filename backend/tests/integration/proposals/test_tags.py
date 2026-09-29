"""AC-PROP-1/a, AC-PROP-7 and AC-IP-5 on the real tag route (REQ-PROP-03, REQ-NOT-02; docs/spec/06 6.3, 6.10).

- Tagging Safaricom (E2), Airtel (E2), Telkom (E0) and an E1 organisation creates two delivered tags with their
  ``SUBMITTED`` engagements and two held tags; the E1 organisation sees only a count; EM1 lists the sent and saved
  groups and is sent exactly once, to the developer only.
- One open engagement or held tag per (developer, organisation): tagging it from another proposal returns 409 with the
  reason and creates nothing (a batch is refused whole). A decline holds the organisation back for 30 days.
- Tagging needs D1 (403 ``d1_required``, nothing created); the developer's own organisation, a draft, someone else's
  proposal or an unlisted organisation are refused; a held tag can be withdrawn, a delivered one cannot.
- The ``TagHooks`` seam (P3's grant, P5's engagement) is called for delivered tags only, and a failing hook rolls the
  whole Pitch back.
"""

from __future__ import annotations

import asyncio
import contextlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.notifications import em1
from tests.integration.api import make_client, outbox
from tests.integration.proposals.helpers import Developers, ProposalWorld, create, draft_body, published, rows, user_of
from tests.integration.proposals.pitch_helpers import (
    Members,
    PitchOrgs,
    RecordingHooks,
    add_org,
    counts,
    install,
    org_mail,
    pitch,
    pitchable,
    sent,
)

E0_SENTENCE = (
    "isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify."
    " We don't email them on your behalf."
)


async def test_mixed_tags(
    developers: Developers,
    proposal_world: ProposalWorld,
    pitch_orgs: PitchOrgs,
    owner_engine: AsyncEngine,
    member_client: Members,
) -> None:
    """AC-PROP-1/a with the EM1 clause (REQ-NOT-02)."""
    dev, proposal_id = await pitchable(developers, proposal_world, title="Cold-chain alerts")
    hooks = install(dev, RecordingHooks())
    orgs = pitch_orgs
    response = await pitch(dev, proposal_id, *orgs.cast())
    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["sent_count"], result["saved_count"], result["email_sent"]) == (2, 2, True)
    assert result["cap"] == {"used": 4, "limit": 5, "plan": "dev_free"}
    statuses = {tag["org"]["name"]: tag["status"] for tag in result["tags"]}
    assert statuses == {
        orgs.safaricom.name: "delivered",
        orgs.airtel.name: "delivered",
        orgs.telkom.name: "held_unclaimed",
        orgs.claimed.name: "held_pending_verification",
    }
    by_org = {tag["org"]["id"]: tag for tag in result["tags"]}
    for org in (orgs.safaricom, orgs.airtel):
        assert by_org[str(org.id)]["engagement_id"] is not None
        assert by_org[str(org.id)]["message"] is None
    for org in (orgs.telkom, orgs.claimed):
        assert by_org[str(org.id)]["engagement_id"] is None
        assert by_org[str(org.id)]["open"] is True
    assert by_org[str(orgs.telkom.id)]["message"] == f"{orgs.telkom.name} {E0_SENTENCE}"

    # Two SUBMITTED engagements (origin tagged, the current version), each with its genesis event.
    engagements = await rows(
        owner_engine,
        "SELECT e.org_id, e.state, e.origin, e.version_id = p.current_version_id AS current,"
        " (SELECT count(*) FROM engagement_events ev WHERE ev.engagement_id = e.id) AS events"
        " FROM engagements e JOIN proposals p ON p.id = e.proposal_id WHERE e.proposal_id = :p",
        p=proposal_id,
    )
    assert {(r.org_id, r.state, r.origin, r.current, r.events) for r in engagements} == {
        (orgs.safaricom.id, "SUBMITTED", "tagged", True, 1),
        (orgs.airtel.id, "SUBMITTED", "tagged", True, 1),
    }
    # The hooks ran for the delivered tags only, in order, with the contract's arguments.
    assert [call["org_id"] for call in hooks.engagements] == [orgs.safaricom.id, orgs.airtel.id]
    assert [call["org_id"] for call in hooks.grants] == [orgs.safaricom.id, orgs.airtel.id]
    assert hooks.engagements[0]["developer_id"] == user_of(dev)
    assert hooks.grants[0] == {"owner_id": user_of(dev), "proposal_id": UUID(proposal_id), "org_id": orgs.safaricom.id}
    tag_ids = {UUID(by_org[str(orgs.safaricom.id)]["id"]), UUID(by_org[str(orgs.airtel.id)]["id"])}
    assert {call["tag_id"] for call in hooks.engagements} == tag_ids

    # The E1 organisation sees only a count; the E2 organisations see the proposal in their Inbox.
    claimed = await member_client(orgs.claimed.member)  # type: ignore[arg-type]
    e1_inbox = (await claimed.get(f"/api/orgs/{orgs.claimed.id}/inbox")).json()
    assert (e1_inbox["items"], e1_inbox["held_count"], e1_inbox["verification"]) == ([], 1, "e1")
    reviewer = await member_client(orgs.safaricom.member)  # type: ignore[arg-type]
    [item] = (await reviewer.get(f"/api/orgs/{orgs.safaricom.id}/inbox")).json()["items"]
    assert item["proposal"]["id"] == proposal_id
    assert item["engagement"]["id"] == by_org[str(orgs.safaricom.id)]["engagement_id"]
    assert item["engagement"]["state"] == "SUBMITTED"

    # EM1: exactly one email, to the developer, listing both groups; nothing to any organisation.
    [message] = sent(dev)
    assert message.to.endswith("@example.test")
    assert message.subject == 'Your proposal "Cold-chain alerts" is registered and sent to 2 organisations'
    assert f"Sent to (2 organisations, verified):\n- {orgs.safaricom.name}\n- {orgs.airtel.name}\n" in message.text
    assert "Saved for (2 organisations):" in message.text
    assert f"- {orgs.telkom.name} {E0_SENTENCE}" in message.text
    assert f"- {orgs.claimed.name} is still verifying its details." in message.text
    assert "Timestamp pending" in message.text
    [delivery] = await rows(
        owner_engine, "SELECT kind, status, dedupe_key FROM notification_deliveries WHERE user_id = :u", u=user_of(dev)
    )
    assert (delivery.kind, delivery.status) == ("em1", "sent")
    [note] = await rows(owner_engine, "SELECT kind, link FROM in_app_notifications WHERE user_id = :u", u=user_of(dev))
    assert (note.kind, note.link) == ("pitch_sent", f"/dev/ideas/{proposal_id}")
    assert await org_mail(owner_engine, [*orgs.cast(), orgs.bystander]) == 0

    # Exactly once: delivering the same Pitch again sends nothing more.
    pending = em1.PendingEm1(
        user_of(dev), message.to, em1.EmailParts(message.subject, message.text, message.html or ""), delivery.dedupe_key
    )
    await em1.deliver(dev.app.state.session_factory, outbox(dev), pending)  # type: ignore[attr-defined]
    assert len(sent(dev)) == 1
    assert (await counts(owner_engine, user_of(dev)))["deliveries"] == 1


async def test_a_second_pitch_sends_its_own_em1(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    assert (await pitch(dev, proposal_id, pitch_orgs.safaricom)).status_code == 201
    assert (await pitch(dev, proposal_id, pitch_orgs.airtel)).status_code == 201
    first, second = sent(dev)
    assert first.subject.endswith("sent to 1 organisation")
    assert pitch_orgs.airtel.name in second.text
    assert pitch_orgs.safaricom.name not in second.text
    assert (await counts(owner_engine, user_of(dev)))["deliveries"] == 2


async def test_duplicate_org_409(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    """AC-PROP-7: an open engagement (or held tag) with an organisation from a first proposal; tagging it from a
    second proposal returns 409 with the reason and creates nothing."""
    dev, first = await pitchable(developers, proposal_world, title="First idea")
    second = (await published(dev, proposal_world, title="Second idea"))["proposal_id"]
    assert (await pitch(dev, first, pitch_orgs.safaricom, pitch_orgs.telkom)).status_code == 201
    before = await counts(owner_engine, user_of(dev))
    emails = len(sent(dev))
    for org in (pitch_orgs.safaricom, pitch_orgs.telkom):
        refused = await pitch(dev, second, org)
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "tag_conflict"
        assert detail["conflicts"] == [
            {
                "org_id": str(org.id),
                "reason": "open_elsewhere",
                "message": f"You already have an open pitch with {org.name}. One open pitch per organisation at a"
                " time: wait for its answer or withdraw it first.",
            }
        ]
    # A batch with one conflict is refused whole: Airtel is not tagged either.
    batch = await pitch(dev, second, pitch_orgs.airtel, pitch_orgs.safaricom)
    assert batch.status_code == 409
    assert [c["org_id"] for c in batch.json()["detail"]["conflicts"]] == [str(pitch_orgs.safaricom.id)]
    # The same proposal again: "already pitched to it".
    again = await pitch(dev, first, pitch_orgs.safaricom)
    assert again.json()["detail"]["conflicts"][0]["reason"] == "tagged"
    assert await counts(owner_engine, user_of(dev)) == before
    assert len(sent(dev)) == emails


async def test_tag_requires_d1(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    """AC-IP-5 on the tag route: below D1 (or without a developer profile) 403 ``d1_required``, nothing created."""
    dev, proposal_id = await pitchable(developers, proposal_world)
    developer_id = user_of(dev)
    level = "UPDATE developer_profiles SET verification_level = CAST(:level AS dev_verification) WHERE user_id = :u"
    async with owner_engine.begin() as conn:
        await conn.execute(text(level), {"level": "d0", "u": developer_id})
    refused = await pitch(dev, proposal_id, pitch_orgs.safaricom, pitch_orgs.telkom)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "d1_required"
    assert (await counts(owner_engine, developer_id))["tags"] == 0
    async with owner_engine.begin() as conn:
        await conn.execute(text(level), {"level": "d1", "u": developer_id})
    assert (await pitch(dev, proposal_id, pitch_orgs.safaricom, pitch_orgs.telkom)).status_code == 201

    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM developer_profiles WHERE user_id = :u"), {"u": developer_id})
    no_profile = await pitch(dev, proposal_id, pitch_orgs.airtel)
    assert no_profile.status_code == 403
    assert no_profile.json()["detail"]["code"] == "d1_required"


async def test_what_cannot_be_pitched(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    developer_id = user_of(dev)
    draft = await create(dev, draft_body(proposal_world))
    not_public = await pitch(dev, draft["id"], pitch_orgs.safaricom)
    assert (not_public.status_code, not_public.json()["detail"]["code"]) == (409, "proposal_not_public")
    _, others = await pitchable(developers, proposal_world)
    assert (await pitch(dev, others, pitch_orgs.safaricom)).status_code == 404  # someone else's proposal
    unknown = await pitch(dev, proposal_id, pitch_orgs.safaricom.id, UUID(int=1))
    assert (unknown.status_code, unknown.json()["detail"]["org_ids"]) == (404, [str(UUID(int=1))])
    delisted = await add_org(owner_engine, "Gone", verification="unclaimed", niche_id=None, roles=None)
    pending = await add_org(owner_engine, "Pending", verification="pending", niche_id=None, roles=None)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE organizations SET delisted_at = now() WHERE id = :id"), {"id": delisted.id})
    for unlisted in (delisted, pending):
        assert (await pitch(dev, proposal_id, unlisted)).status_code == 404
    # Your own organisation, and a suspended verified one.
    async with owner_engine.begin() as conn:
        await add_member_of(conn, pitch_orgs.bystander.id, developer_id)
    suspended = await add_org(owner_engine, "Suspended", verification="e2", niche_id=None, suspended=True)
    refused = await pitch(dev, proposal_id, pitch_orgs.bystander, suspended)
    assert refused.status_code == 409
    assert [(c["org_id"], c["reason"]) for c in refused.json()["detail"]["conflicts"]] == [
        (str(pitch_orgs.bystander.id), "own_organisation"),
        (str(suspended.id), "unavailable"),
    ]
    assert (await counts(owner_engine, developer_id))["tags"] == 0


async def add_member_of(conn: object, org_id: UUID, user_id: UUID) -> None:
    await conn.execute(  # type: ignore[attr-defined]
        text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (uuid7(), :org, :user, '{viewer}')"),
        {"org": org_id, "user": user_id},
    )


async def test_a_held_tag_can_be_withdrawn_and_a_delivered_one_cannot(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, first = await pitchable(developers, proposal_world)
    second = (await published(dev, proposal_world, title="Another idea"))["proposal_id"]
    tags = (await pitch(dev, first, pitch_orgs.telkom, pitch_orgs.safaricom)).json()["tags"]
    held, delivered = tags[0]["id"], tags[1]["id"]
    withdrawn = await dev.post(f"/api/me/proposals/{first}/tags/{held}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert (withdrawn.json()["status"], withdrawn.json()["open"], withdrawn.json()["message"]) == (
        "withdrawn",
        False,
        None,
    )
    again = await dev.post(f"/api/me/proposals/{first}/tags/{held}/withdraw")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "tag_closed")
    kept = await dev.post(f"/api/me/proposals/{first}/tags/{delivered}/withdraw")
    assert (kept.status_code, kept.json()["detail"]["code"]) == (409, "tag_delivered")
    assert (await dev.post(f"/api/me/proposals/{second}/tags/{held}/withdraw")).status_code == 404  # wrong proposal
    stranger = await developers()
    assert (await stranger.post(f"/api/me/proposals/{first}/tags/{held}/withdraw")).status_code == 404
    # Withdrawn, the organisation is free again (from another proposal), and the slot no longer counts.
    assert (await pitch(dev, second, pitch_orgs.telkom)).status_code == 201
    listing = (await dev.get(f"/api/me/proposals/{first}/tags")).json()
    assert [t["status"] for t in listing["items"]] == ["withdrawn", "delivered"]
    assert listing["cap"]["used"] == 1


async def test_a_failing_hook_rolls_the_pitch_back(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    hooks = install(dev, RecordingHooks(fail=True))
    with contextlib.suppress(RuntimeError):  # the in-process transport re-raises the handler's error (a 500)
        await pitch(dev, proposal_id, pitch_orgs.telkom, pitch_orgs.safaricom)
    assert len(hooks.grants) == 1
    assert (await counts(owner_engine, user_of(dev))) == {
        "tags": 0,
        "engagements": 0,
        "deliveries": 0,
        "in_app": 0,
        "pitched": 0,
    }
    assert sent(dev) == []


async def test_a_decline_holds_the_organisation_back_for_30_days(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, first = await pitchable(developers, proposal_world)
    second = (await published(dev, proposal_world, title="Later idea"))["proposal_id"]
    tag = (await pitch(dev, first, pitch_orgs.safaricom)).json()["tags"][0]
    async with owner_engine.begin() as conn:  # the organisation declines (P5's command; written here as the owner)
        await conn.execute(
            text(
                "INSERT INTO engagement_events (id, engagement_id, actor_role, command, from_state, to_state,"
                " end_reason) VALUES (uuid7(), :e, 'system', 'decline', 'SUBMITTED', 'DECLINED', 'NOT_PRIORITY')"
            ),
            {"e": tag["engagement_id"]},
        )
        await conn.execute(text("UPDATE tags SET closed_at = now() WHERE id = :t"), {"t": tag["id"]})
        clock = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
    refused = await pitch(dev, second, pitch_orgs.safaricom)
    assert refused.status_code == 409
    assert refused.json()["detail"]["conflicts"][0]["reason"] == "cooldown"
    again = await pitch(dev, first, pitch_orgs.safaricom)
    assert again.json()["detail"]["conflicts"][0]["reason"] == "already_pitched"
    try:
        async with owner_engine.begin() as conn:  # 31 days on the shared clock
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = interval '31 days'"))
        assert (await pitch(dev, second, pitch_orgs.safaricom)).status_code == 201
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :enabled, clock_offset = :offset"),
                {"enabled": clock.enabled, "offset": clock.clock_offset},
            )


async def test_concurrent_pitches_to_one_organisation_create_one_tag(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, first = await pitchable(developers, proposal_world)
    second = (await published(dev, proposal_world, title="Parallel idea"))["proposal_id"]
    twin = await developers(user_id=user_of(dev))  # a second session of the same developer
    answers = await asyncio.gather(pitch(dev, first, pitch_orgs.airtel), pitch(twin, second, pitch_orgs.airtel))
    assert sorted(a.status_code for a in answers) == [201, 409]
    assert (await counts(owner_engine, user_of(dev)))["tags"] == 1


async def test_the_picker_groups_by_niche_with_levels_and_availability(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world)
    draft = await create(dev, draft_body(proposal_world))
    assert (await pitch(dev, proposal_id, pitch_orgs.safaricom)).status_code == 201
    response = await dev.get(f"/api/me/proposals/{draft['id']}/pitch/orgs", params={"q": pitch_orgs.tag})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["proposal_public"] is False
    assert page["cap"] == {"used": 0, "limit": 5, "plan": "dev_free"}
    [group] = page["groups"]
    assert group["niche"]["label"] == proposal_world.niche_label
    options = {o["card"]["name"]: o for o in group["orgs"]}
    assert set(options) == {o.name for o in (*pitch_orgs.cast(), pitch_orgs.bystander)}
    assert options[pitch_orgs.safaricom.name]["outcome"] == "delivered"
    assert options[pitch_orgs.claimed.name]["outcome"] == "held_pending_verification"
    telkom = options[pitch_orgs.telkom.name]
    assert (telkom["outcome"], telkom["available"]) == ("held_unclaimed", True)
    assert telkom["message"] == f"{pitch_orgs.telkom.name} {E0_SENTENCE}"
    safaricom = options[pitch_orgs.safaricom.name]
    assert (safaricom["available"], safaricom["reason"]) == (False, "open_elsewhere")  # open from the first proposal
    mine = (await dev.get(f"/api/me/proposals/{proposal_id}/pitch/orgs", params={"q": pitch_orgs.tag})).json()
    assert mine["proposal_public"] is True
    assert mine["cap"]["used"] == 1
    [group] = mine["groups"]
    assert {o["card"]["name"]: o["reason"] for o in group["orgs"]}[pitch_orgs.safaricom.name] == "tagged"
    stranger = await developers()
    assert (await stranger.get(f"/api/me/proposals/{proposal_id}/pitch/orgs")).status_code == 404
    assert (await stranger.get(f"/api/me/proposals/{proposal_id}/tags")).status_code == 404
    bad = await dev.get(f"/api/me/proposals/{proposal_id}/pitch/orgs", params={"cursor": "nope"})
    assert (bad.status_code, bad.json()["detail"]["code"]) == (400, "invalid_cursor")


async def test_signed_out_callers_get_401(app_engine: AsyncEngine, pitch_orgs: PitchOrgs) -> None:
    async with make_client(app_engine) as anonymous:
        some = "01920000-0000-7000-8000-000000000000"
        assert (await anonymous.get(f"/api/me/proposals/{some}/tags")).status_code == 401
        assert (await anonymous.post(f"/api/me/proposals/{some}/tags", json={"org_ids": [some]})).status_code == 401
        assert (await anonymous.get(f"/api/orgs/{pitch_orgs.safaricom.id}/inbox")).status_code == 401
