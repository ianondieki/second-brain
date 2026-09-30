"""REQ-BIL-08 (P14): who may start, read and settle a checkout, and activation exactly once under parallel reads.

- A developer's checkout is theirs alone: another developer, or any organisation member, gets the same 404 as for an
  id that does not exist, and their read never asks the provider or settles anything.
- An organisation's checkout is started and read by its owner, admin or finance members only: a non-member gets 404,
  another role 403 on start and 404 on read; a payer of another organisation gets 404.
- Parallel reads of one checkout (one app, or two payers of one organisation) activate the plan once; parallel starts
  of the same plan make one payment.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.billing.providers.fake import FakePaymentProvider
from bridge.ids import uuid7
from tests.integration.api import make_client, sign_in_as
from tests.integration.billing.checkout_helpers import (
    audit_actions,
    buy,
    install,
    instant,
    live_plans,
    payment_row,
    payments_of,
    slow,
    status_of,
)
from tests.integration.proposals.helpers import Developers, rows, user_of
from tests.integration.proposals.pitch_helpers import Members, Org, add_member, add_org

pytestmark = pytest.mark.usefixtures("plans_seeded")

NOT_FOUND = {"code": "not_found", "message": "Not found."}


async def _org_with(owner_engine: AsyncEngine, *roles: str) -> tuple[Org, dict[str, UUID]]:
    """An E1 organisation and one member per role (owners, admins and reviewers have TOTP; all are signed in with the
    second factor by ``member_client``)."""
    org = await add_org(owner_engine, f"Payco {uuid7().hex[-6:]}", verification="e1", niche_id=None, roles=None)
    members: dict[str, UUID] = {}
    async with owner_engine.begin() as conn:
        for role in roles:
            members[role] = await add_member(conn, org.id, f"{{{role}}}")
    return org, members


async def test_a_developers_checkout_is_invisible_to_everyone_else(
    developers: Developers, member_client: Members, owner_engine: AsyncEngine
) -> None:
    owner = await developers()
    slow(owner)
    checkout_id = (await buy(owner, "dev_pro_monthly")).json()["id"]

    stranger = await developers()
    instant(stranger)  # were the read to reach a provider, this one would settle it at once (unknown: failed)
    _, members = await _org_with(owner_engine, "owner", "finance")
    outsiders = [stranger, await member_client(members["owner"]), await member_client(members["finance"])]
    for outsider in outsiders:
        instant(outsider)
        for read in (await status_of(outsider, checkout_id), await status_of(outsider, str(uuid7()))):
            assert (read.status_code, read.json()["detail"]) == (404, NOT_FOUND)
    row = await payment_row(owner_engine, checkout_id)
    assert (row.status, row.subscription_id, row.settled_at) == ("pending", None, None)
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started"]
    # The same id in another's start body is refused before anything is read (no id is ever taken from a client).
    assert (await buy(stranger, "dev_pro_monthly", id=checkout_id)).status_code == 422
    assert await payments_of(owner_engine, user=user_of(stranger)) == []


async def test_an_organisations_plan_is_paid_by_its_owner_admin_or_finance_members(
    member_client: Members, owner_engine: AsyncEngine
) -> None:
    org, members = await _org_with(owner_engine, "owner", "admin", "finance", "reviewer", "signatory", "viewer")
    finance = await member_client(members["finance"])
    provider = instant(finance)
    started = await buy(finance, "org_starter", org_id=str(org.id))
    assert started.status_code == 201, started.text
    body = started.json()
    assert (body["org_id"], body["side"], body["amount_kes_minor"]) == (str(org.id), "org", 1_500_000)
    row = await payment_row(owner_engine, body["id"])
    assert (row.org_id, row.user_id, row.initiated_by) == (org.id, None, members["finance"])

    # Other roles: 403 to start, 404 to read. The owner and the admin read it (the same subject).
    for role in ("reviewer", "signatory", "viewer"):
        client = await member_client(members[role])
        install(client, provider)
        refused = await buy(client, "org_growth", org_id=str(org.id))
        assert refused.status_code == 403
        assert refused.json()["detail"] == {"code": "forbidden", "message": "You do not have access to this action."}
        read = await status_of(client, body["id"])
        assert (read.status_code, read.json()["detail"]) == (404, NOT_FOUND)
    assert (await payment_row(owner_engine, body["id"])).status == "pending"
    for role in ("owner", "admin"):
        client = await member_client(members[role])
        install(client, provider)
        assert (await status_of(client, body["id"])).json()["status"] == "succeeded"
    assert await live_plans(owner_engine, org=org.id) == ["org_starter"]
    reviewer = await member_client(members["reviewer"])
    ent = (await reviewer.get(f"/api/orgs/{org.id}/entitlements")).json()
    assert (ent["plan"], ent["limits"]["seats"]) == ("org_starter", 5)
    assert len(await payments_of(owner_engine, org=org.id)) == 1


async def test_payers_of_another_organisation_and_non_members_get_404(
    member_client: Members, owner_engine: AsyncEngine
) -> None:
    org, members = await _org_with(owner_engine, "finance")
    other, other_members = await _org_with(owner_engine, "owner", "finance")
    finance = await member_client(members["finance"])
    slow(finance)
    checkout_id = (await buy(finance, "org_growth", org_id=str(org.id))).json()["id"]
    for role in ("owner", "finance"):
        outsider = await member_client(other_members[role])
        instant(outsider)
        read = await status_of(outsider, checkout_id)
        assert (read.status_code, read.json()["detail"]) == (404, NOT_FOUND)
        refused = await buy(outsider, "org_growth", org_id=str(org.id))  # not a member of org
        assert (refused.status_code, refused.json()["detail"]) == (404, NOT_FOUND)
    assert (await payment_row(owner_engine, checkout_id)).status == "pending"
    assert len(await payments_of(owner_engine, org=org.id)) == 1
    assert await payments_of(owner_engine, org=other.id) == []


async def test_parallel_reads_activate_the_plan_once(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    instant(client)
    checkout_id = (await buy(client, "dev_pro_monthly")).json()["id"]
    reads = await asyncio.gather(*(status_of(client, checkout_id) for _ in range(8)))
    assert {r.status_code for r in reads} == {200}
    assert {(r.json()["status"], r.json()["plan_active"]) for r in reads} == {("succeeded", True)}
    assert await live_plans(owner_engine, user=user_of(client)) == ["dev_pro_monthly"]
    subscriptions = await rows(owner_engine, "SELECT id FROM subscriptions WHERE user_id = :u", u=user_of(client))
    assert len(subscriptions) == 1
    assert (await payment_row(owner_engine, checkout_id)).subscription_id == subscriptions[0].id
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started", "billing.checkout_settled"]


async def test_two_payers_reading_at_once_activate_once(member_client: Members, owner_engine: AsyncEngine) -> None:
    org, members = await _org_with(owner_engine, "owner", "finance")
    owner = await member_client(members["owner"])
    finance = await member_client(members["finance"])
    provider = install(finance, FakePaymentProvider(delay=timedelta(0)))
    install(owner, provider)  # one API process, one provider
    checkout_id = (await buy(finance, "org_growth", org_id=str(org.id))).json()["id"]
    reads = await asyncio.gather(*(status_of(c, checkout_id) for c in (owner, finance, owner, finance)))
    assert {r.json()["status"] for r in reads} == {"succeeded"}
    assert await live_plans(owner_engine, org=org.id) == ["org_growth"]
    subscriptions = await rows(owner_engine, "SELECT id FROM subscriptions WHERE org_id = :o", o=org.id)
    assert len(subscriptions) == 1
    assert await audit_actions(owner_engine, checkout_id) == ["billing.checkout_started", "billing.checkout_settled"]


async def test_parallel_starts_of_one_plan_make_one_payment(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    slow(client)
    started = await asyncio.gather(*(buy(client, "dev_pro_monthly") for _ in range(4)))
    assert sorted(r.status_code for r in started) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in started}) == 1
    assert len(await payments_of(owner_engine, user=user_of(client))) == 1


async def test_an_organisations_owner_needs_the_second_factor_to_pay_or_poll(
    app_engine: AsyncEngine, member_client: Members, owner_engine: AsyncEngine
) -> None:
    """The organisation's rules apply to its checkouts: an owner (TOTP required) whose session has not done the
    second factor can neither start nor read one, though RLS would show them the row."""
    org, members = await _org_with(owner_engine, "owner", "finance")
    finance = await member_client(members["finance"])
    slow(finance)
    checkout_id = (await buy(finance, "org_starter", org_id=str(org.id))).json()["id"]
    async with make_client(app_engine) as owner:
        await sign_in_as(owner, app_engine, members["owner"], mfa_verified=False)
        instant(owner)
        for response in (await buy(owner, "org_growth", org_id=str(org.id)), await status_of(owner, checkout_id)):
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "mfa_required"
    assert (await payment_row(owner_engine, checkout_id)).status == "pending"
