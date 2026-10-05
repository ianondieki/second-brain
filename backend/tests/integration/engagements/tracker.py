"""Fixtures for the tracker schema tests (revision 0003): the two parties of an engagement, outsiders, and a walk
along the main path that writes each step's evidence as the party that makes it.

Every helper runs inside one rolled-back transaction of the owner engine (``as_app``): fixtures are written as the
owner, then the connection switches to ``bridge_app`` acting for a user (``act``), as the application does.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w

PDF_SHA256 = bytes(range(32))
CERTIFICATE_SHA256 = bytes(range(32, 64))


@asynccontextmanager
async def as_app(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One rolled-back transaction: fixtures are written as the owner, then the connection acts as bridge_app."""
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


async def run(conn: AsyncConnection, sql: str, **params: object) -> Any:
    """Execute ``sql``; the first column of the first row when it returns rows."""
    result = await conn.execute(sa.text(sql), params)
    return result.scalar() if result.returns_rows else None


async def rowcount(conn: AsyncConnection, sql: str, **params: object) -> int:
    result = await conn.execute(sa.text(sql), params)
    return int(result.rowcount)


async def act(conn: AsyncConnection, user_id: UUID | None, org_id: UUID | None = None) -> None:
    """Switch the connection to bridge_app acting for ``user_id`` (and ``org_id``)."""
    await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
    await conn.execute(
        sa.text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
        {"u": str(user_id) if user_id else "", "o": str(org_id) if org_id else ""},
    )


async def as_owner(conn: AsyncConnection) -> None:
    await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))


async def backend_pid(conn: AsyncConnection) -> int:
    return int(await run(conn, "SELECT pg_backend_pid()"))


async def wait_until_blocked(observer: AsyncConnection, pid: int, statement: asyncio.Task[Any]) -> None:
    """Wait until the backend ``pid``, running ``statement``, waits for a lock (pg_locks shows a lock it asked for and
    was not granted; pg_locks is read live, not from a snapshot). Fails if the statement finishes first (it did not
    wait) or nothing waits within 30 seconds."""
    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted")
    deadline = time.monotonic() + 30
    while not (await observer.execute(blocked, {"pid": pid})).scalar_one():
        assert not statement.done(), "the statement did not wait for the lock"
        assert time.monotonic() < deadline, "the statement never waited for the lock"
        await asyncio.sleep(0.01)  # a poll interval: the order comes from the lock, not from a delay


async def expect(conn: AsyncConnection, sql: str, match: str, **params: object) -> None:
    """Run ``sql`` in a savepoint, assert it fails with ``match``, and leave the outer transaction usable."""
    savepoint = await conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        await conn.execute(sa.text(sql), params)
    await savepoint.rollback()


def _email(prefix: str, domain: str = "example.test") -> str:
    return f"{prefix}-{uuid4().hex[:10]}@{domain}"


@dataclass(frozen=True, slots=True)
class Parties:
    developer: UUID  # D2, TOTP enrolled; owns the proposal
    org: UUID  # E2, verified domain
    owner: UUID  # the organisation's owner and admin
    signatory: UUID  # TOTP enrolled
    reviewer: UUID
    finance: UUID
    viewer: UUID
    proposal: UUID
    version: UUID
    outsider: UUID  # another developer, with a published proposal of their own
    other_org: UUID  # another E2 organisation
    other_member: UUID  # its owner, admin and signatory
    staff: UUID  # staff admin with TOTP


async def _user(conn: AsyncConnection, prefix: str, domain: str = "example.test", *, totp: bool = False) -> UUID:
    user_id = uuid7()
    now = datetime.now(UTC)
    await run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
        " VALUES (:id, :email, :name, :now, :totp)",
        id=user_id,
        email=_email(prefix, domain),
        name=prefix.title(),
        now=now,
        totp=now if totp else None,
    )
    return user_id


async def _org(conn: AsyncConnection, domain: str, verification: str = "e2") -> UUID:
    org_id = uuid7()
    await run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain)"
        " VALUES (:id, 'company', 'Tracker Ltd', :slug, 'seed', CAST(:verification AS org_verification), :domain)",
        id=org_id,
        slug=f"tracker-{org_id.hex}",
        verification=verification,
        domain=domain,
    )
    return org_id


async def member(conn: AsyncConnection, org: UUID, user: UUID, roles: str) -> None:
    await run(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS org_role[]))",
        id=uuid7(),
        org=org,
        user=user,
        roles=roles,
    )


async def tag(conn: AsyncConnection, proposal: UUID, org: UUID, developer: UUID) -> UUID:
    tag_id = uuid7()
    await run(
        conn,
        "INSERT INTO tags (id, proposal_id, org_id, developer_id, status) VALUES (:id, :p, :org, :dev, 'delivered')",
        id=tag_id,
        p=proposal,
        org=org,
        dev=developer,
    )
    return tag_id


async def parties(conn: AsyncConnection) -> Parties:
    """As the owner: a D2 developer with a published proposal tagged to an E2 organisation and its members, an outside
    developer, another E2 organisation, and staff admin. The developer's tag to the organisation is delivered."""
    domain = f"tracker-{uuid4().hex[:10]}.example.test"
    developer = await _user(conn, "developer", totp=True)
    org = await _org(conn, domain)
    owner = await _user(conn, "owner", domain)
    signatory = await _user(conn, "signatory", domain, totp=True)
    reviewer = await _user(conn, "reviewer", domain)
    finance = await _user(conn, "finance", domain)
    viewer = await _user(conn, "viewer", domain)
    for user, roles in (
        (owner, "{owner,admin}"),
        (signatory, "{signatory}"),
        (reviewer, "{reviewer}"),
        (finance, "{finance}"),
        (viewer, "{viewer}"),
    ):
        await member(conn, org, user, roles)
    niche = uuid7()
    await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Tracker')", id=niche, s=f"t-{niche.hex}")
    problem = await w.add_problem(conn, developer, niche)
    proposal, version = await w.add_proposal(conn, developer, niche, problem)
    await run(conn, "UPDATE developer_profiles SET verification_level = 'd2' WHERE user_id = :u", u=developer)
    await tag(conn, proposal, org, developer)
    outsider = await _user(conn, "outsider", totp=True)
    await w.add_proposal(conn, outsider, niche, problem)
    other_domain = f"other-{uuid4().hex[:10]}.example.test"
    other_org = await _org(conn, other_domain)
    other_member = await _user(conn, "other", other_domain, totp=True)
    await member(conn, other_org, other_member, "{owner,admin,signatory}")
    staff = await w.add_user(conn, _email("staff"), "Staff", staff_role="admin")
    return Parties(
        developer=developer,
        org=org,
        owner=owner,
        signatory=signatory,
        reviewer=reviewer,
        finance=finance,
        viewer=viewer,
        proposal=proposal,
        version=version,
        outsider=outsider,
        other_org=other_org,
        other_member=other_member,
        staff=staff,
    )


ENGAGE = (
    "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state)"
    " VALUES (:id, :p, :org, :dev, :v, CAST(:origin AS engagement_origin), CAST(:state AS engagement_state))"
)


async def engage(conn: AsyncConnection, p: Parties, *, origin: str = "tagged", state: str = "SUBMITTED") -> UUID:
    """The developer creates the engagement of their tag (a signatory, the org's ORG_INTEREST), as bridge_app."""
    engagement_id = uuid7()
    await run(
        conn,
        ENGAGE,
        id=engagement_id,
        p=p.proposal,
        org=p.org,
        dev=p.developer,
        v=p.version,
        origin=origin,
        state=state,
    )
    return engagement_id


APPEND = (
    "INSERT INTO engagement_events (id, engagement_id, actor_user_id, actor_role, command, from_state, to_state,"
    " end_reason, stage_deadline_at, payload) VALUES (:id, :e, :actor, CAST(:role AS engagement_actor_role), :command,"
    " CAST(:from_state AS engagement_state), CAST(:to_state AS engagement_state),"
    " CAST(:reason AS engagement_end_reason), :deadline, CAST(:payload AS jsonb))"
)


def event_params(
    engagement: UUID,
    actor: UUID | None,
    role: str,
    command: str,
    from_state: str | None,
    to_state: str,
    *,
    reason: str | None = None,
    deadline: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "e": engagement,
        "actor": actor,
        "role": role,
        "command": command,
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,
        "deadline": deadline,
        "payload": json.dumps(payload or {}),
    }


async def append(
    conn: AsyncConnection,
    engagement: UUID,
    actor: UUID | None,
    role: str,
    command: str,
    from_state: str,
    to_state: str,
    **kwargs: Any,
) -> UUID:
    """Append one event as ``actor`` in ``role`` (the connection already acts for the actor); returns its id."""
    params = event_params(engagement, actor, role, command, from_state, to_state, **kwargs)
    await conn.execute(sa.text(APPEND), params)
    return UUID(str(params["id"]))


async def state_of(conn: AsyncConnection, engagement: UUID) -> str:
    return str(await run(conn, "SELECT state::text FROM engagements WHERE id = :id", id=engagement))


ENDORSE = (
    "INSERT INTO engagement_endorsements (id, engagement_id, stage, milestone_id, party, user_id, role, method)"
    " VALUES (:id, :e, CAST(:stage AS engagement_state), :milestone, CAST(:party AS engagement_party), :user,"
    " CAST(:role AS engagement_actor_role), CAST(:method AS endorsement_method))"
)
SIGN = (
    "INSERT INTO signatures (id, engagement_id, document_kind, document_ref, document_sha256, signer_user_id, party,"
    " step_up_method, ip, user_agent) VALUES (:id, :e, CAST(:kind AS signature_document_kind), :ref, :sha, :signer,"
    " CAST(:party AS engagement_party), CAST(:method AS step_up_method), '198.51.100.7', 'pytest')"
)
RECORD_PAYMENT = (
    "INSERT INTO payment_records (id, engagement_id, milestone_id, amount_kes_minor, method, reference, paid_on,"
    " recorded_by) VALUES (:id, :e, :milestone, :amount, 'mpesa', 'QK12AB34CD', :paid_on, :by)"
)


def sign_params(
    engagement: UUID, kind: str, ref: UUID, sha: bytes, signer: UUID, party: str, method: str = "totp"
) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "e": engagement,
        "kind": kind,
        "ref": ref,
        "sha": sha,
        "signer": signer,
        "party": party,
        "method": method,
    }


def payment_params(engagement: UUID, by: UUID, amount: int, milestone: UUID | None = None) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "e": engagement,
        "milestone": milestone,
        "amount": amount,
        "paid_on": date.today() - timedelta(days=1),  # noqa: DTZ011  # the day before, whatever the zone
        "by": by,
    }


async def signed(conn: AsyncConnection, engagement: UUID, kind: str, ref: UUID, party: str) -> bool:
    """Whether ``party`` signed that document (read under the caller's RLS: a party sees every signature)."""
    found = await run(
        conn,
        "SELECT count(*) FROM signatures WHERE engagement_id = :e"
        " AND document_kind = CAST(:k AS signature_document_kind) AND document_ref = :r"
        " AND party = CAST(:p AS engagement_party)",
        e=engagement,
        k=kind,
        r=ref,
        p=party,
    )
    return bool(found)


async def document_ref(conn: AsyncConnection, engagement: UUID, command: str) -> UUID:
    """The document the latest ``command`` event named (the mutual NDA sent, the certificate of an accepted delivery),
    as P5's commands record it; a new id for an event written without one."""
    ref = await run(
        conn,
        "SELECT payload->>'document_ref' FROM engagement_events WHERE engagement_id = :e AND command = :c"
        " ORDER BY seq DESC LIMIT 1",
        e=engagement,
        c=command,
    )
    return UUID(ref) if ref else uuid7()


@dataclass(slots=True)
class Walk:
    """What a walk along the main path created."""

    engagement: UUID
    agreement: UUID | None = None
    milestone: UUID | None = None
    certificate: UUID | None = None
    payment: UUID | None = None


MAIN_PATH = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTEREST_CONFIRMED",
    "CONTACT_MADE",
    "NDA_PENDING",
    "NDA_SIGNED",
    "NEGOTIATION",
    "AGREEMENT_SIGNING",
    "IN_IMPLEMENTATION",
    "DELIVERED",
    "SIGN_OFF",
    "PAYMENT_FINAL",
    "CLOSED",
)
FINAL_AMOUNT = 25_000_000  # KES 250,000.00 in cents


async def walk(conn: AsyncConnection, p: Parties, engagement: UUID, until: str) -> Walk:
    """Take an engagement along the main path from where it is to ``until``, each step (and its evidence) written as
    bridge_app by the party that makes it; evidence a test already wrote (the agreement, a signature) is reused. Leaves
    the connection acting for the developer."""
    done = Walk(engagement)
    await as_owner(conn)
    existing = await conn.execute(
        sa.text(
            "SELECT a.id, (SELECT m.id FROM milestones m WHERE m.agreement_id = a.id ORDER BY m.seq LIMIT 1)"
            " FROM agreements a WHERE a.engagement_id = :e AND a.version = 1"
        ),
        {"e": engagement},
    )
    for agreement, milestone in existing.all():
        done.agreement, done.milestone = agreement, milestone
    stop = MAIN_PATH.index(until)
    for index in range(MAIN_PATH.index(await state_of(conn, engagement)), stop):
        here, there = MAIN_PATH[index], MAIN_PATH[index + 1]
        if there == "UNDER_REVIEW":
            await act(conn, p.reviewer, p.org)
            await append(conn, engagement, p.reviewer, "reviewer", "start_review", here, there)
        elif there == "INTEREST_CONFIRMED":
            await act(conn, p.signatory, p.org)
            await run(
                conn,
                "UPDATE engagements SET contact_user_id = :c, contact_channel = 'email', contact_by = :by"
                " WHERE id = :id",
                c=p.owner,
                by=date(2026, 12, 1),
                id=engagement,
            )
            await append(conn, engagement, p.signatory, "signatory", "approve", here, there)
        elif there == "CONTACT_MADE":
            await act(conn, p.owner, p.org)
            await append(conn, engagement, p.owner, "owner", "mark_contacted", here, there)
            await run(
                conn,
                ENDORSE,
                id=uuid7(),
                e=engagement,
                stage=there,
                milestone=None,
                party="org",
                user=p.owner,
                role="owner",
                method="click",
            )
        elif there == "NDA_PENDING":
            await act(conn, p.developer)
            await run(
                conn,
                ENDORSE,
                id=uuid7(),
                e=engagement,
                stage=here,
                milestone=None,
                party="developer",
                user=p.developer,
                role="developer",
                method="click",
            )
            # P5's commands name the sent document in the event (bridge.engagements.service reads it back).
            payload = {"document_ref": str(uuid7()), "document_sha256": PDF_SHA256.hex()}
            await append(conn, engagement, p.developer, "developer", "send_nda", here, there, payload=payload)
        elif there == "NDA_SIGNED":
            nda = await document_ref(conn, engagement, "send_nda")
            await act(conn, p.developer)
            await run(conn, SIGN, **sign_params(engagement, "mutual_nda", nda, PDF_SHA256, p.developer, "developer"))
            await act(conn, p.signatory, p.org)
            await run(conn, SIGN, **sign_params(engagement, "mutual_nda", nda, PDF_SHA256, p.signatory, "org"))
            await append(conn, engagement, p.signatory, "signatory", "sign_nda", here, there)
        elif there == "NEGOTIATION":
            done.agreement, done.milestone = uuid7(), uuid7()
            await act(conn, p.developer)
            await run(
                conn,
                "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 1, :by)",
                id=done.agreement,
                e=engagement,
                by=p.developer,
            )
            await run(
                conn,
                "INSERT INTO milestones (id, agreement_id, engagement_id, seq, deliverable, amount_kes_minor, due_date,"
                " review_window_bd) VALUES (:id, :a, :e, 1, 'Pilot for one county', :amount, :due, 5)",
                id=done.milestone,
                a=done.agreement,
                e=engagement,
                amount=FINAL_AMOUNT,
                due=date(2027, 3, 31),
            )
            await append(conn, engagement, p.developer, "developer", "upload_terms", here, there)
        elif there == "AGREEMENT_SIGNING":
            await act(conn, p.signatory, p.org)
            await run(
                conn,
                "UPDATE agreements SET ip_terms = 'non_exclusive_licence', deemed_acceptance_days = 10,"
                " final_pdf_sha256 = :sha, status = 'final' WHERE id = :id",
                sha=PDF_SHA256,
                id=done.agreement,
            )
            await append(conn, engagement, p.signatory, "signatory", "mark_final", here, there)
        elif there == "IN_IMPLEMENTATION":
            assert done.agreement is not None
            if not await signed(conn, engagement, "agreement", done.agreement, "developer"):
                await act(conn, p.developer)
                params = sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.developer, "developer")
                await run(conn, SIGN, **(params | {"method": "passkey"}))
            await act(conn, p.signatory, p.org)
            if not await signed(conn, engagement, "agreement", done.agreement, "org"):
                await run(
                    conn, SIGN, **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.signatory, "org")
                )
            await run(conn, "UPDATE agreements SET status = 'signed' WHERE id = :id", id=done.agreement)
            await append(conn, engagement, p.signatory, "signatory", "sign_agreement", here, there)
        elif there == "DELIVERED":
            await act(conn, p.developer)
            for step in ("IN_PROGRESS", "SUBMITTED_FOR_REVIEW"):
                await run(
                    conn,
                    "UPDATE milestones SET state = CAST(:s AS milestone_state) WHERE id = :id",
                    s=step,
                    id=done.milestone,
                )
            await act(conn, p.reviewer, p.org)
            await run(conn, "UPDATE milestones SET state = 'ACCEPTED' WHERE id = :id", id=done.milestone)
            await act(conn, p.developer)
            await append(conn, engagement, p.developer, "developer", "deliver", here, there)
        elif there == "SIGN_OFF":
            await act(conn, p.signatory, p.org)
            payload = {"document_ref": str(uuid7()), "document_sha256": CERTIFICATE_SHA256.hex()}
            await append(conn, engagement, p.signatory, "signatory", "accept_delivery", here, there, payload=payload)
        elif there == "PAYMENT_FINAL":
            done.certificate = await document_ref(conn, engagement, "accept_delivery")
            await act(conn, p.signatory, p.org)
            cert = sign_params(
                engagement, "acceptance_certificate", done.certificate, CERTIFICATE_SHA256, p.signatory, "org"
            )
            await run(conn, SIGN, **cert)
            await act(conn, p.developer)
            cert = cert | {"id": uuid7(), "signer": p.developer, "party": "developer"}
            await run(conn, SIGN, **cert)
            await append(conn, engagement, p.developer, "developer", "countersign", here, there)
        elif there == "CLOSED":
            payment = payment_params(engagement, p.finance, FINAL_AMOUNT)
            done.payment = UUID(str(payment["id"]))
            await act(conn, p.finance, p.org)
            await run(conn, RECORD_PAYMENT, **payment)
            await act(conn, p.developer)
            await run(
                conn,
                "UPDATE payment_records SET confirmed_by = :me, confirmed_amount_kes_minor = :amount WHERE id = :id",
                me=p.developer,
                amount=FINAL_AMOUNT,
                id=done.payment,
            )
            await append(conn, engagement, p.developer, "developer", "confirm_payment", here, there)
    await act(conn, p.developer)
    assert await state_of(conn, engagement) == until
    return done
