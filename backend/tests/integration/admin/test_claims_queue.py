"""REQ-DIR-03 queue (REQ-ADM-01; docs/spec/06 6.2, 6.12; PLAN §8 P15): the staff admin's claims queue, read only.

- ``GET /api/admin/claims`` and ``GET /api/admin/claims/{id}`` answer a staff admin with TOTP and a fresh second
  factor; everyone else gets the console's 404 (signed out, a developer, staff without TOTP), a moderator or support
  403, an admin with a stale second factor 403 ``step_up_required``.
- ``?view=review`` (the default) lists the claims awaiting staff (``pending_review`` and ``disputed``) oldest first,
  each ``pending_review`` claim with its 2-business-day review SLA (policy.yaml ``claims.review_sla_bd``) from the
  claim's submission; a dispute carries its open ``claim_dispute`` moderation case instead. ``in_progress`` lists the
  claims still waiting for the claimant, ``closed`` the decided and withdrawn ones, newest first.
- The detail adds the evidence (the domain email, the proofs, the E2 facts, a document count), the organisation's
  official domains and its other open claims, and the moderation cases about the claim; never the OTP digest or the
  DNS token.
- Read only (the prototype decides no claim, ``app_decide_claim`` is not called): no other method exists on either
  path, and reading changes no claim and writes no audit event.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.calendar import add_business_days, business_days_between, local_date
from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as

BASE = "/api/admin/claims"
OLD = datetime(2026, 3, 3, 7, 0, tzinfo=UTC)  # a Tuesday, 10:00 in Nairobi; no Kenyan holiday that week


class Client(Protocol):
    def __call__(self, user_id: UUID, *, fresh: bool = True) -> Awaitable[httpx.AsyncClient]: ...


@pytest.fixture
async def as_user(app_engine: AsyncEngine) -> AsyncIterator[Client]:
    async with AsyncExitStack() as stack:

        async def make(user_id: UUID, *, fresh: bool = True) -> httpx.AsyncClient:
            client = await stack.enter_async_context(make_client(app_engine))
            await sign_in_as(client, app_engine, user_id, mfa_verified=fresh)
            return client

        yield make


async def _rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _user(owner_engine: AsyncEngine, name: str, *, staff_role: str | None = None) -> UUID:
    async with owner_engine.begin() as conn:
        return await w.add_user(conn, f"{name.lower()}-{uuid7().hex[-10:]}@example.test", name, staff_role=staff_role)


@dataclass(frozen=True, slots=True)
class ClaimsWorld:
    admin: UUID
    open_org: UUID  # unclaimed, listed: B (old, E2) and C (fresh, E1) await review, D is still at the email code
    held_org: UUID  # A holds an approved claim; E's later claim competes with it (a dispute)
    hidden_org: UUID  # delisted: staff cannot read the organisation (F awaits review)
    tag: str
    domain: str
    a: UUID
    b: UUID
    c: UUID
    d: UUID
    e: UUID
    f: UUID
    dispute_case: UUID

    @property
    def ids(self) -> set[str]:
        return {str(claim) for claim in (self.a, self.b, self.c, self.d, self.e, self.f)}


async def _org(conn: Any, tag: str, name: str, *, domain: str | None = None, delisted: bool = False) -> UUID:
    org_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO organizations"
            " (id, kind, legal_name, slug, source, verification, official_domains, delisted_at)"
            " VALUES (:id, 'ngo_pbo', :name, :slug, 'admin', 'unclaimed', CAST(:domains AS citext[]),"
            " CASE WHEN :delisted THEN now() END)"
        ),
        {
            "id": org_id,
            "name": f"{name} {tag}",
            "slug": f"{name.lower().replace(' ', '-')}-{tag}",
            "domains": [domain] if domain else [],
            "delisted": delisted,
        },
    )
    return org_id


async def _claim(
    conn: Any,
    org: UUID,
    user: UUID,
    domain: str,
    *,
    level: str,
    status: str,
    created_at: datetime | None = None,
    **facts: Any,
) -> UUID:
    """A claim as the claimant's flow would leave it (written as the owner role: the guard trigger still runs)."""
    claim_id = uuid7()
    columns = {
        "id": claim_id,
        "org_id": org,
        "claimant_user_id": user,
        "domain": domain,
        "email_address": f"claims-{user.hex[-6:]}@{domain}",
        "level": level,
        "status": status,
        **facts,
    }
    names = ", ".join(columns)
    values = ", ".join(
        f"CAST(:{name} AS {'claim_level' if name == 'level' else 'claim_status'})"
        if name in ("level", "status")
        else f":{name}"
        for name in columns
    )
    await conn.execute(text(f"INSERT INTO org_claims ({names}) VALUES ({values})"), columns)
    if created_at is not None:  # org_claims_guard stamps now(): date it as the scenario needs
        await conn.execute(
            text("UPDATE org_claims SET created_at = :at, updated_at = :at WHERE id = :id"),
            {"at": created_at, "id": claim_id},
        )
    return claim_id


@pytest.fixture
async def claims(owner_engine: AsyncEngine) -> ClaimsWorld:
    tag = uuid7().hex[-8:]
    domain = f"claims-{tag}.example.test"
    admin = await _user(owner_engine, "Admin", staff_role="admin")
    names = ["Achieng", "Baraka", "Chebet", "Dalmas", "Esther", "Faraji"]
    people = {name: await _user(owner_engine, name) for name in names}
    async with owner_engine.begin() as conn:
        open_org = await _org(conn, tag, "Open Org", domain=domain)
        held_org = await _org(conn, tag, "Held Org")
        hidden_org = await _org(conn, tag, "Hidden Org", delisted=True)
        a = await _claim(
            conn,
            held_org,
            people["Achieng"],
            f"held-{tag}.example.test",
            level="e1",
            status="approved",
            created_at=OLD - timedelta(days=30),
            decided_at=OLD - timedelta(days=29),
        )
        b = await _claim(
            conn,
            open_org,
            people["Baraka"],
            domain,
            level="e2",
            status="pending_review",
            created_at=OLD,
            registration_no="PBO-TEST-0001",
            kra_pin="P000000000Z",
            sector_register="PBO Authority",
            public_entity_requested=False,
            document_keys=["claims/b/letter.pdf", "claims/b/cr12.pdf"],
        )
        e = await _claim(
            conn,
            held_org,
            people["Esther"],
            f"held-{tag}.example.test",
            level="e1",
            status="pending_review",
            created_at=OLD + timedelta(days=7),
        )
        c = await _claim(conn, open_org, people["Chebet"], domain, level="e1", status="pending_review")
        d = await _claim(conn, open_org, people["Dalmas"], domain, level="e1", status="otp_sent")
        f = await _claim(
            conn,
            hidden_org,
            people["Faraji"],
            f"hidden-{tag}.example.test",
            level="e1",
            status="pending_review",
            created_at=OLD + timedelta(days=1),
        )
        dispute_case = uuid7()
        await conn.execute(
            text(
                "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source)"
                " VALUES (:id, 'org_claim', :claim, ARRAY['competing_claim'], 'claim_dispute')"
            ),
            {"id": dispute_case, "claim": e},
        )
    [status] = await _rows(owner_engine, "SELECT status::text FROM org_claims WHERE id = :id", id=e)
    assert status[0] == "disputed"  # the guard filed it as a dispute: A holds an approved claim on the organisation
    return ClaimsWorld(admin, open_org, held_org, hidden_org, tag, domain, a, b, c, d, e, f, dispute_case)


def _ours(body: dict[str, Any], world: ClaimsWorld) -> list[dict[str, Any]]:
    return [item for item in body["items"] if item["id"] in world.ids]


async def _now_and_holidays(owner_engine: AsyncEngine) -> tuple[datetime, frozenset[date]]:
    [now] = await _rows(owner_engine, "SELECT app_clock_now()")
    days = await _rows(owner_engine, "SELECT observed_on FROM holidays WHERE country = 'KE'")
    return now[0], frozenset(day[0] for day in days)


# ------------------------------------------------------------------------------------------------------- access


async def test_the_claims_queue_is_staff_admin_only_with_a_fresh_second_factor(
    claims: ClaimsWorld, as_user: Client, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    paths = (BASE, f"{BASE}?view=closed", f"{BASE}/{claims.b}", f"{BASE}/{uuid7()}")
    async with make_client(app_engine) as anonymous:
        for path in paths:
            assert (await anonymous.get(path)).status_code == 404, path
    no_totp = await _user(owner_engine, "NoTotp", staff_role="admin")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET totp_enabled_at = NULL WHERE id = :id"), {"id": no_totp})
    developer = await as_user(await _user(owner_engine, "Developer"))
    admin_without_totp = await as_user(no_totp)
    moderator = await as_user(await _user(owner_engine, "Moderator", staff_role="moderator"))
    support = await as_user(await _user(owner_engine, "Support", staff_role="support"))
    stale = await as_user(claims.admin, fresh=False)
    for path in paths:
        for hidden in (developer, admin_without_totp):
            response = await hidden.get(path)
            assert response.status_code == 404, path
            assert response.json() == {"detail": {"code": "not_found", "message": "Not found."}}
        for staff in (moderator, support):
            refused = await staff.get(path)
            assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "forbidden"), path
        refused = await stale.get(path)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "step_up_required"), path
    admin = await as_user(claims.admin)
    assert (await admin.get(BASE)).status_code == 200
    unknown = await admin.get(f"{BASE}/{uuid7()}")
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "not_found")
    assert (await admin.get(BASE, params={"view": "everything"})).status_code == 422


# -------------------------------------------------------------------------------------------------------- queue


async def test_the_review_queue_lists_claims_awaiting_staff_oldest_first_with_the_sla(
    claims: ClaimsWorld, as_user: Client, owner_engine: AsyncEngine
) -> None:
    admin = await as_user(claims.admin)
    response = await admin.get(BASE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_sla_bd"] == 2
    queue = _ours(body, claims)
    assert [item["id"] for item in queue] == [str(claims.b), str(claims.f), str(claims.e), str(claims.c)]
    assert body == (await admin.get(BASE, params={"view": "review"})).json()

    now, holidays = await _now_and_holidays(owner_engine)
    old, hidden, disputed, fresh = queue
    assert old["sla"] == {
        "due_on": "2026-03-05",
        "business_days_left": old["sla"]["business_days_left"],
        "overdue": True,
    }
    assert old["sla"]["business_days_left"] < 0
    today = local_date(now)
    assert fresh["sla"] == {
        "due_on": add_business_days(today, 2, holidays).isoformat(),
        "business_days_left": 2,
        "overdue": False,
    }
    assert disputed["sla"] is None  # a dispute is reviewed through its moderation case, not the review SLA
    assert disputed["status"] == "disputed"
    assert disputed["dispute_case_id"] == str(claims.dispute_case)
    assert old["dispute_case_id"] is None

    assert old["org"] == {
        "id": str(claims.open_org),
        "legal_name": f"Open Org {claims.tag}",
        "slug": f"open-org-{claims.tag}",
        "kind": "ngo_pbo",
        "verification": "unclaimed",
    }
    assert old["claimant"] == {"id": old["claimant"]["id"], "display_name": "Baraka"}
    assert (old["domain"], old["level"], old["status"]) == (claims.domain, "e2", "pending_review")
    assert (old["otp_verified"], old["dns_verified"]) == (False, False)
    assert old["created_at"].startswith("2026-03-03T07:00:00")
    # A delisted organisation is not readable by staff under RLS (listed ones only): its claim still shows.
    assert hidden["org"] == {
        "id": str(claims.hidden_org),
        "legal_name": None,
        "slug": None,
        "kind": None,
        "verification": None,
    }
    assert hidden["claimant"]["display_name"] == "Faraji"
    for item in queue:
        assert "email_address" not in item  # the detail's only
        assert "otp_hash" not in item
        assert "dns_token" not in item


async def test_the_review_sla_skips_kenyan_holidays_only(
    claims: ClaimsWorld, as_user: Client, owner_engine: AsyncEngine
) -> None:
    """B was submitted on Tuesday 2026-03-03: due Thursday, or Friday once Wednesday is a Kenyan holiday. A holiday of
    another country (here the Friday) moves nothing. The rows are this test's own and are removed afterwards."""
    name = f"P15 test holiday {claims.tag}"
    count = "SELECT count(*) FROM holidays"
    [before] = await _rows(owner_engine, count)
    async with owner_engine.begin() as conn:
        for country, day in (("KE", date(2026, 3, 4)), ("UG", date(2026, 3, 6))):
            await conn.execute(
                text(
                    "INSERT INTO holidays (id, country, holiday_on, observed_on, name)"
                    " VALUES (:id, :country, :day, :day, :name)"
                ),
                {"id": uuid7(), "country": country, "day": day, "name": name},
            )
    try:
        admin = await as_user(claims.admin)
        [listed] = [item for item in (await admin.get(BASE)).json()["items"] if item["id"] == str(claims.b)]
        detail = (await admin.get(f"{BASE}/{claims.b}")).json()
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM holidays WHERE name = :name"), {"name": name})
    assert await _rows(owner_engine, count) == [before]
    assert (listed["sla"]["due_on"], listed["sla"]["overdue"]) == ("2026-03-06", True)
    assert detail["sla"] == listed["sla"]
    now, holidays = await _now_and_holidays(owner_engine)
    today = local_date(now)
    # Late by the Kenyan business days since the due day (the seeded holidays of the months since are not counted).
    assert listed["sla"]["business_days_left"] == -business_days_between(date(2026, 3, 6), today, holidays)


async def test_the_other_views_list_claims_in_progress_and_closed(claims: ClaimsWorld, as_user: Client) -> None:
    admin = await as_user(claims.admin)
    in_progress = _ours((await admin.get(BASE, params={"view": "in_progress"})).json(), claims)
    assert [(item["id"], item["status"], item["sla"]) for item in in_progress] == [(str(claims.d), "otp_sent", None)]
    closed = _ours((await admin.get(BASE, params={"view": "closed"})).json(), claims)
    assert [(item["id"], item["status"], item["sla"]) for item in closed] == [(str(claims.a), "approved", None)]


async def test_closed_claims_come_newest_decision_first(
    claims: ClaimsWorld, as_user: Client, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        later = await _claim(
            conn,
            claims.hidden_org,
            await w.add_user(conn, f"g-{uuid7().hex[-8:]}@example.test", "Gathoni"),
            f"g-{claims.domain}",
            level="e1",
            status="rejected",
            created_at=OLD - timedelta(days=60),
            decided_at=OLD - timedelta(days=2),
        )
    admin = await as_user(claims.admin)
    closed = [
        item["id"]
        for item in (await admin.get(BASE, params={"view": "closed"})).json()["items"]
        if item["id"] in {str(later), str(claims.a)}
    ]
    assert closed == [str(later), str(claims.a)]  # decided 2 days before OLD, then 29 days before


async def test_the_detail_shows_the_evidence_the_other_open_claims_and_the_cases(
    claims: ClaimsWorld, as_user: Client
) -> None:
    admin = await as_user(claims.admin)
    detail = (await admin.get(f"{BASE}/{claims.b}")).json()
    listed = next(item for item in (await admin.get(BASE)).json()["items"] if item["id"] == str(claims.b))
    assert {key: detail[key] for key in listed} == listed  # the detail is the list item and more
    assert detail["email_address"].endswith(f"@{claims.domain}")
    assert (detail["otp_verified_at"], detail["dns_verified_at"]) == (None, None)
    assert (detail["otp_attempts"], detail["otp_reissues"]) == (0, 0)
    assert (detail["registration_no"], detail["kra_pin"], detail["sector_register"]) == (
        "PBO-TEST-0001",
        "P000000000Z",
        "PBO Authority",
    )
    assert (detail["cr12_date"], detail["public_entity_requested"], detail["document_count"]) == (None, False, 2)
    assert "document_keys" not in detail  # storage keys stay server-side: no download path in the prototype
    assert (detail["official_domains"], detail["verified_domain"], detail["domain_is_official"]) == (
        [claims.domain],
        None,
        True,
    )
    assert (detail["reviewed_by"], detail["decided_at"], detail["decision_reason"]) == (None, None, None)
    assert [(o["id"], o["claimant"]["display_name"], o["status"]) for o in detail["other_claims"]] == [
        (str(claims.c), "Chebet", "pending_review"),
        (str(claims.d), "Dalmas", "otp_sent"),
    ]
    assert detail["cases"] == []
    assert "otp_hash" not in detail
    assert "dns_token" not in detail

    disputed = (await admin.get(f"{BASE}/{claims.e}")).json()
    assert disputed["other_claims"] == []  # A's claim is decided, not open
    assert [(case["id"], case["source"], case["status"]) for case in disputed["cases"]] == [
        (str(claims.dispute_case), "claim_dispute", "open")
    ]
    assert disputed["domain_is_official"] is False


# ---------------------------------------------------------------------------------------------------- read only


async def test_claims_are_read_only(claims: ClaimsWorld, as_user: Client, owner_engine: AsyncEngine) -> None:
    ids = sorted(claims.ids)
    snapshot = (
        "SELECT id, status::text, reviewed_by, decided_at, decision_reason, updated_at, otp_attempts"
        " FROM org_claims WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
    )
    before = await _rows(owner_engine, snapshot, ids=ids)
    admin = await as_user(claims.admin)
    for view in ("review", "in_progress", "closed"):
        assert (await admin.get(BASE, params={"view": view})).status_code == 200
    for claim in ids:
        assert (await admin.get(f"{BASE}/{claim}")).status_code == 200
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in (BASE, f"{BASE}/{claims.b}", f"{BASE}/{claims.b}/decision"):
            response = await admin.request(method, path, json={"decision": "approve"})
            assert response.status_code in (404, 405), (method, path)
    assert await _rows(owner_engine, snapshot, ids=ids) == before
    audit = "SELECT id FROM audit_events WHERE subject_id = ANY(CAST(:ids AS uuid[]))"
    assert await _rows(owner_engine, audit, ids=ids) == []
    paths = admin.app.openapi()["paths"]  # type: ignore[attr-defined]
    assert set(paths[BASE]) == {"get"}
    assert set(paths[BASE + "/{claim_id}"]) == {"get"}
    assert not [path for path in paths if path.startswith(BASE + "/{claim_id}/")]
