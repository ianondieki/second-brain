"""REQ-ENG-01 (schema half; AC-TRACK-1 403 half, AC-TRACK-7 and AC-TRACK-10 database halves), D-37 and the dev/test
clock (revision 0003).

- Parties only: another developer and another organisation's members read nothing of an engagement and write
  nothing into it; staff admin reads every tracker row and writes none; each row names its actor as the caller, in a
  role the caller holds.
- The main path runs SUBMITTED -> ... -> CLOSED through the database with each step's evidence: IN_IMPLEMENTATION
  needs a signed agreement, PAYMENT_FINAL the acceptance certificate signed by both parties, CLOSED the developer's
  confirmation of the final payment at the recorded amount; the internal e-signature refuses an assignment.
- Endorsements are of the current stage, once per party and stage entry; agreements freeze when final; milestones
  follow the sub-tracker with each step by its party; a payment is recorded by the organisation and confirmed once by
  the developer, and never deleted.
- ``users.demo_account`` is set by the owner only; the test clock moves forward only, only where the owner enabled
  it, and every tracker time follows it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from bridge.auth.models import User
from bridge.engagements import chain
from bridge.ids import uuid7
from tests.integration.engagements.tracker import (
    APPEND,
    CERTIFICATE_SHA256,
    ENDORSE,
    ENGAGE,
    FINAL_AMOUNT,
    PDF_SHA256,
    RECORD_PAYMENT,
    SIGN,
    act,
    append,
    as_app,
    as_owner,
    engage,
    event_params,
    expect,
    member,
    parties,
    payment_params,
    rowcount,
    run,
    sign_params,
    state_of,
    tag,
    walk,
)

TRACKER_TABLES = (
    "engagement_events",
    "engagement_endorsements",
    "agreements",
    "milestones",
    "signatures",
    "payment_records",
)


def endorse_params(
    engagement: UUID,
    stage: str,
    party: str,
    user: UUID | None,
    role: str,
    method: str = "click",
    milestone: UUID | None = None,
) -> dict[str, object]:
    return {
        "id": uuid7(),
        "e": engagement,
        "stage": stage,
        "milestone": milestone,
        "party": party,
        "user": user,
        "role": role,
        "method": method,
    }


async def test_only_the_parties_read_or_write_an_engagement(owner_engine: AsyncEngine) -> None:
    """Another developer and another organisation's member read 0 rows of every tracker table and write nothing into
    the engagement (a cross-tenant write is an RLS refusal, never a row); staff admin reads every row and writes none;
    the organisation's viewer reads but acts in no role; a forged org context does not help."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "PAYMENT_FINAL")  # a row in every tracker table
        assert done.milestone is not None
        await act(conn, p.finance, p.org)
        await run(conn, RECORD_PAYMENT, **payment_params(engagement, p.finance, FINAL_AMOUNT))
        visible = "SELECT count(*) FROM {table} WHERE engagement_id = :e"
        for reader, org in ((p.developer, None), (p.viewer, p.org), (p.reviewer, None), (p.staff, None)):
            await act(conn, reader, org)
            assert await run(conn, "SELECT count(*) FROM engagements WHERE id = :e", e=engagement) == 1
            for table in TRACKER_TABLES:
                assert await run(conn, visible.format(table=table), e=engagement) >= 1, (reader, table)
        for outsider, org in ((p.outsider, None), (p.other_member, p.other_org), (p.other_member, p.org), (None, None)):
            await act(conn, outsider, org)
            assert await run(conn, "SELECT count(*) FROM engagements WHERE id = :e", e=engagement) == 0
            for table in TRACKER_TABLES:
                assert await run(conn, visible.format(table=table), e=engagement) == 0, (outsider, table)
            assert (
                await rowcount(conn, "UPDATE engagements SET contact_by = contact_by WHERE id = :e", e=engagement) == 0
            )
            assert (
                await rowcount(
                    conn, "UPDATE milestones SET state = 'CHANGES_REQUESTED' WHERE id = :m", m=done.milestone
                )
                == 0
            )
            assert (
                await rowcount(
                    conn, "UPDATE payment_records SET confirmed_by = NULL WHERE engagement_id = :e", e=engagement
                )
                == 0
            )
            assert await rowcount(conn, "DELETE FROM milestones WHERE engagement_id = :e", e=engagement) == 0

        for writer, org in ((p.other_member, p.other_org), (p.staff, None)):
            writes = (
                (APPEND, event_params(engagement, writer, "signatory", "note", "PAYMENT_FINAL", "PAYMENT_FINAL")),
                (APPEND, event_params(engagement, None, "system", "note", "PAYMENT_FINAL", "PAYMENT_FINAL")),
                (ENDORSE, endorse_params(engagement, "PAYMENT_FINAL", "org", writer, "signatory")),
                (ENDORSE, endorse_params(engagement, "PAYMENT_FINAL", "org", None, "system", "auto")),
                (SIGN, sign_params(engagement, "mutual_nda", uuid7(), PDF_SHA256, writer, "org", "passkey")),
                (RECORD_PAYMENT, payment_params(engagement, writer, 100)),
                (
                    "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 9, :by)",
                    {"id": uuid7(), "e": engagement, "by": writer},
                ),
            )
            await act(conn, writer, org)
            # An outsider is refused before anything is read (review P1, MAJOR 1); staff read the engagement and are
            # refused by the table's RLS.
            refused = "row-level security" if writer == p.staff else "no engagement of the caller's with that id"
            for sql, params in writes:
                await expect(conn, sql, refused, **params)
        await act(conn, p.staff)
        await expect(
            conn,
            APPEND,
            "row-level security",
            **event_params(engagement, p.staff, "owner", "note", "PAYMENT_FINAL", "PAYMENT_FINAL"),
        )


async def test_each_row_names_its_actor_in_a_role_they_hold(owner_engine: AsyncEngine) -> None:
    """AC-TRACK-1 (database half of 403): the developer acts only as the developer, a member only in a role they hold
    (a viewer in none), nobody names another user, and a system event names nobody and comes from a party's job."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        refused = (
            (p.developer, None, p.developer, "signatory"),  # the developer is no member
            (p.viewer, p.org, p.viewer, "reviewer"),  # a role they do not hold
            (p.viewer, p.org, p.viewer, "viewer"),  # not an actor role at all
            (p.reviewer, p.org, p.signatory, "signatory"),  # another user as actor
            (p.reviewer, p.org, p.reviewer, "developer"),
            (p.developer, None, None, "developer"),  # a user event names its actor
        )
        for caller, org, actor, role in refused:
            await act(conn, caller, org)
            params = event_params(engagement, actor, role, "note", "SUBMITTED", "SUBMITTED")
            await expect(conn, APPEND, "row-level security|invalid input value|ck_engagement_events_actor", **params)
        await as_owner(conn)  # the CHECK holds for every role: a system event names nobody, a user event its actor
        for actor, role in ((p.reviewer, "system"), (None, "reviewer")):
            params = event_params(engagement, actor, role, "note", "SUBMITTED", "SUBMITTED")
            await expect(conn, APPEND, "ck_engagement_events_actor_matches_role", **params)
        await act(conn, p.reviewer, p.org)
        await append(conn, engagement, p.reviewer, "reviewer", "note", "SUBMITTED", "SUBMITTED")
        await append(conn, engagement, None, "system", "remind", "SUBMITTED", "SUBMITTED")  # a job bound to a party
        await act(conn, p.developer)
        await append(conn, engagement, p.developer, "developer", "note", "SUBMITTED", "SUBMITTED")
        roles = await conn.execute(
            sa.text("SELECT actor_role::text FROM engagement_events WHERE engagement_id = :e ORDER BY seq"),
            {"e": engagement},
        )
        assert roles.scalars().all() == ["developer", "reviewer", "system", "developer"]


async def test_the_main_path_runs_to_closed_only_with_its_evidence(owner_engine: AsyncEngine) -> None:
    """SUBMITTED -> CLOSED with each step's evidence; each legal step is refused until its evidence exists
    (AC-TRACK-10, AC-TRACK-7); the chain verifies for both parties and the engagement ends at CLOSED."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "NEGOTIATION")
        assert done.agreement is not None
        assert done.milestone is not None

        # Marking final needs the IP terms, the clause and the PDF hash (CHECK) and a milestone (trigger).
        await act(conn, p.signatory, p.org)
        await expect(
            conn,
            "UPDATE agreements SET status = 'final' WHERE id = :a",
            "ck_agreements_final_is_complete",
            a=done.agreement,
        )
        await expect(
            conn,
            "UPDATE agreements SET status = 'signed' WHERE id = :a",
            "marked final before it is signed",
            a=done.agreement,
        )
        bare = uuid7()
        await run(
            conn,
            "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 2, :by)",
            id=bare,
            e=engagement,
            by=p.signatory,
        )
        await expect(
            conn,
            "UPDATE agreements SET ip_terms = 'revenue_share', deemed_acceptance_days = 0, final_pdf_sha256 = :sha,"
            " status = 'final' WHERE id = :a",
            "needs at least one milestone",
            sha=PDF_SHA256,
            a=bare,
        )
        draft = "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 3, :by)"
        await expect(conn, draft, "row-level security", id=uuid7(), e=engagement, by=p.developer)  # not as another
        await act(conn, p.reviewer, p.org)  # a reviewer drafts nothing
        await expect(
            conn,
            "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 3, :by)",
            "row-level security",
            id=uuid7(),
            e=engagement,
            by=p.reviewer,
        )

        await walk(conn, p, engagement, "AGREEMENT_SIGNING")
        await act(conn, p.signatory, p.org)
        # Frozen once final: its terms, its milestones' plan, and no new or removed milestone.
        await expect(conn, "UPDATE agreements SET ip_terms = 'assignment' WHERE id = :a", "frozen", a=done.agreement)
        await expect(conn, "UPDATE agreements SET status = 'draft' WHERE id = :a", "frozen", a=done.agreement)
        await expect(conn, "UPDATE milestones SET amount_kes_minor = 1 WHERE id = :m", "frozen", m=done.milestone)
        await expect(conn, "DELETE FROM milestones WHERE id = :m", "never deleted", m=done.milestone)
        await expect(
            conn,
            "INSERT INTO milestones (id, agreement_id, engagement_id, seq, deliverable, amount_kes_minor, due_date,"
            " review_window_bd) VALUES (:id, :a, :e, 2, 'More', 100, '2027-01-01', 5)",
            "planned while their agreement is a draft",
            id=uuid7(),
            a=done.agreement,
            e=engagement,
        )
        # IN_IMPLEMENTATION needs the agreement signed by both parties.
        into_implementation = event_params(
            engagement, p.signatory, "signatory", "sign_agreement", "AGREEMENT_SIGNING", "IN_IMPLEMENTATION"
        )
        await expect(conn, APPEND, "needs an agreement signed by both parties", **into_implementation)
        # Signatures: the final PDF's hash only; a D1 developer cannot sign an agreement; one signature per party.
        await expect(
            conn,
            SIGN,
            "the final PDF",
            **sign_params(engagement, "agreement", done.agreement, CERTIFICATE_SHA256, p.signatory, "org"),
        )
        await act(conn, p.reviewer, p.org)  # only a signatory signs for the organisation
        await expect(
            conn,
            SIGN,
            "row-level security",
            **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.reviewer, "org", "passkey"),
        )
        await as_owner(conn)
        await run(conn, "UPDATE developer_profiles SET verification_level = 'd1' WHERE user_id = :u", u=p.developer)
        await act(conn, p.developer)
        await expect(
            conn,
            SIGN,
            "row-level security",
            **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.developer, "developer"),
        )
        await as_owner(conn)
        await run(conn, "UPDATE developer_profiles SET verification_level = 'd2' WHERE user_id = :u", u=p.developer)
        await act(conn, p.developer)
        await run(
            conn, SIGN, **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.developer, "developer")
        )
        await expect(
            conn,
            SIGN,
            "uq_signatures",
            **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.developer, "developer"),
        )
        await expect(
            conn, "UPDATE agreements SET status = 'signed' WHERE id = :a", "once both parties signed", a=done.agreement
        )
        await walk(conn, p, engagement, "IN_IMPLEMENTATION")
        await expect(conn, "UPDATE agreements SET status = 'final' WHERE id = :a", "frozen", a=done.agreement)

        await walk(conn, p, engagement, "SIGN_OFF")
        # PAYMENT_FINAL needs one acceptance certificate signed by both parties.
        await act(conn, p.signatory, p.org)
        certificate = uuid7()
        await run(
            conn,
            SIGN,
            **sign_params(engagement, "acceptance_certificate", certificate, CERTIFICATE_SHA256, p.signatory, "org"),
        )
        await act(conn, p.developer)
        into_payment = event_params(engagement, p.developer, "developer", "countersign", "SIGN_OFF", "PAYMENT_FINAL")
        await expect(conn, APPEND, "acceptance certificate signed by both", **into_payment)
        other_certificate = sign_params(
            engagement, "acceptance_certificate", uuid7(), CERTIFICATE_SHA256, p.developer, "developer"
        )
        await run(conn, SIGN, **other_certificate)  # a different document is not a countersignature
        await expect(conn, APPEND, "acceptance certificate signed by both", **into_payment | {"id": uuid7()})
        await as_owner(conn)  # nor is one person signing for both sides (MINOR 7; only the owner could write it)
        one_person = uuid7()
        for side in ("org", "developer"):
            await run(
                conn,
                SIGN,
                **sign_params(
                    engagement, "acceptance_certificate", one_person, CERTIFICATE_SHA256, p.signatory, side, "passkey"
                ),
            )
        await act(conn, p.developer)
        await expect(conn, APPEND, "acceptance certificate signed by both", **into_payment | {"id": uuid7()})
        await run(
            conn,
            SIGN,
            **sign_params(
                engagement, "acceptance_certificate", certificate, CERTIFICATE_SHA256, p.developer, "developer"
            ),
        )
        await append(conn, engagement, p.developer, "developer", "countersign", "SIGN_OFF", "PAYMENT_FINAL")

        # CLOSED needs the developer's confirmation of the final payment at the recorded amount (a mismatch is a
        # dispute, never a close: AC-TRACK-7).
        await act(conn, p.finance, p.org)
        short = payment_params(engagement, p.finance, FINAL_AMOUNT)
        await run(conn, RECORD_PAYMENT, **short)
        await act(conn, p.developer)
        close = event_params(engagement, p.developer, "developer", "confirm_payment", "PAYMENT_FINAL", "CLOSED")
        await expect(conn, APPEND, "confirmation of the final payment", **close)
        await run(
            conn,
            "UPDATE payment_records SET confirmed_by = :me, confirmed_amount_kes_minor = :amount WHERE id = :id",
            me=p.developer,
            amount=FINAL_AMOUNT - 100,
            id=short["id"],
        )
        await expect(conn, APPEND, "confirmation of the final payment", **close | {"id": uuid7()})
        await walk(conn, p, engagement, "CLOSED")
        ended = await run(conn, "SELECT ended_at IS NOT NULL FROM engagements WHERE id = :e", e=engagement)
        assert ended is True
        for party, org in ((p.developer, None), (p.signatory, p.org)):  # both parties verify the same chain
            await act(conn, party, org)
            rows = await chain.load_chain(conn, engagement)
            assert chain.verify_rows(rows) == []
            assert [r.to_state for r in rows if r.to_state != r.from_state][-1] == "CLOSED"


async def test_an_assignment_is_never_signed_internally(owner_engine: AsyncEngine) -> None:
    """AC-TRACK-10: an agreement whose IP terms are an assignment or an exclusive licence is refused by the internal
    e-signature (it needs an advanced e-signature or "signed outside the platform")."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "NEGOTIATION")
        await act(conn, p.signatory, p.org)
        await run(
            conn,
            "UPDATE agreements SET ip_terms = 'exclusive_licence', deemed_acceptance_days = 0,"
            " final_pdf_sha256 = :sha, status = 'final' WHERE id = :a",
            sha=PDF_SHA256,
            a=done.agreement,
        )
        assert done.agreement is not None
        for signer, party in ((p.signatory, "org"), (p.developer, "developer")):
            await act(conn, signer, p.org if party == "org" else None)
            await expect(
                conn,
                SIGN,
                "need an advanced e-signature",
                **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, signer, party, "passkey"),
            )


async def test_endorsements_are_of_the_current_stage_once_per_party_and_entry(owner_engine: AsyncEngine) -> None:
    """A party endorses the stage the engagement is in, once per stage entry; re-entering a stage (a disputed first
    contact returns to stage 3) opens a new round; an automatic endorsement names nobody and is its own party's; a
    TOTP endorsement needs TOTP enrolled."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await walk(conn, p, engagement, "CONTACT_MADE")  # the owner endorsed CONTACT_MADE (round 1)
        await act(conn, p.developer)
        await expect(
            conn,
            ENDORSE,
            "only the stage the engagement is in",
            **endorse_params(engagement, "SUBMITTED", "developer", p.developer, "developer"),
        )
        await expect(
            conn,
            ENDORSE,
            "row-level security",
            **endorse_params(engagement, "CONTACT_MADE", "org", p.developer, "owner"),
        )
        await expect(
            conn,
            ENDORSE,
            "row-level security",  # the developer's job cannot endorse the org's side
            **endorse_params(engagement, "CONTACT_MADE", "org", None, "system", "auto"),
        )
        await expect(
            conn,
            ENDORSE,
            "ck_engagement_endorsements_auto_names_nobody",
            **endorse_params(engagement, "CONTACT_MADE", "developer", p.developer, "developer", "auto"),
        )
        # The developer disputes the contact: back to stage 3, then the organisation marks it again.
        await append(
            conn, engagement, p.developer, "developer", "dispute_contact", "CONTACT_MADE", "INTEREST_CONFIRMED"
        )
        await act(conn, p.owner, p.org)
        await append(conn, engagement, p.owner, "owner", "mark_contacted", "INTEREST_CONFIRMED", "CONTACT_MADE")
        await expect(  # checked after RLS (it reads the user), before the endorsement is written
            conn,
            ENDORSE,
            "TOTP endorsement needs TOTP enrolled",
            **endorse_params(engagement, "CONTACT_MADE", "org", p.owner, "owner", "totp"),
        )
        await run(conn, ENDORSE, **endorse_params(engagement, "CONTACT_MADE", "org", p.owner, "owner"))  # round 2
        await act(conn, p.signatory, p.org)  # the organisation's side is endorsed once per entry, whoever endorses
        await expect(
            conn,
            ENDORSE,
            "uq_engagement_endorsements_once",
            **endorse_params(engagement, "CONTACT_MADE", "org", p.signatory, "signatory", "totp"),
        )
        await act(conn, p.developer)  # auto-confirmation after 3 BD: a job bound to the developer
        await run(conn, ENDORSE, **endorse_params(engagement, "CONTACT_MADE", "developer", None, "system", "auto"))
        rounds = await conn.execute(
            sa.text(
                "SELECT stage_round, party::text, method::text, endorsed_at > now() - interval '1 minute'"
                " FROM engagement_endorsements WHERE engagement_id = :e ORDER BY endorsed_at"
            ),
            {"e": engagement},
        )
        assert [tuple(r) for r in rounds.all()] == [
            (1, "org", "click", True),
            (2, "org", "click", True),
            (2, "developer", "auto", True),
        ]


async def test_milestones_move_along_the_sub_tracker_each_step_by_its_party(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "IN_IMPLEMENTATION")
        milestone = done.milestone
        step = "UPDATE milestones SET state = CAST(:s AS milestone_state) WHERE id = :m"
        await act(conn, p.reviewer, p.org)
        await expect(conn, step, "row-level security", s="IN_PROGRESS", m=milestone)  # the developer's step
        await act(conn, p.developer)
        await expect(conn, step, "not a step of the milestone sub-tracker", s="SUBMITTED_FOR_REVIEW", m=milestone)
        await run(conn, step, s="IN_PROGRESS", m=milestone)
        await run(conn, step, s="SUBMITTED_FOR_REVIEW", m=milestone)
        await expect(conn, step, "row-level security", s="ACCEPTED", m=milestone)  # never their own acceptance
        await act(conn, p.viewer, p.org)
        assert await rowcount(conn, "UPDATE milestones SET state = 'ACCEPTED' WHERE id = :m", m=milestone) == 0
        await act(conn, p.reviewer, p.org)
        await run(conn, step, s="CHANGES_REQUESTED", m=milestone)
        await expect(conn, step, "not a step of the milestone sub-tracker", s="ACCEPTED", m=milestone)
        await act(conn, p.developer)
        await run(conn, step, s="IN_PROGRESS", m=milestone)
        await run(conn, step, s="SUBMITTED_FOR_REVIEW", m=milestone)
        await act(conn, p.reviewer, p.org)
        await run(conn, step, s="ACCEPTED", m=milestone)
        await expect(conn, step, "not a step of the milestone sub-tracker", s="CHANGES_REQUESTED", m=milestone)
        await act(conn, p.developer)
        await expect(conn, step, "not a step of the milestone sub-tracker", s="IN_PROGRESS", m=milestone)  # final


async def test_a_payment_is_recorded_by_the_org_and_confirmed_once_by_the_developer(owner_engine: AsyncEngine) -> None:
    """docs/spec/06 6.9 stage 12: the organisation records (KES, method, reference, date; never in the future), the
    developer confirms once with the amount received; nothing else changes and nothing is deleted, for any role. No
    code path moves money: these rows are the only trace of a payment on the platform."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "IN_IMPLEMENTATION")
        for caller, org in ((p.developer, None), (p.viewer, p.org), (p.reviewer, p.org)):
            await act(conn, caller, org)
            await expect(conn, RECORD_PAYMENT, "row-level security", **payment_params(engagement, caller, 100))
        await act(conn, p.finance, p.org)
        await expect(conn, RECORD_PAYMENT, "row-level security", **payment_params(engagement, p.signatory, 100))
        tomorrow = payment_params(engagement, p.finance, 100) | {"paid_on": date.today() + timedelta(days=2)}  # noqa: DTZ011
        await expect(conn, RECORD_PAYMENT, "not dated in the future", **tomorrow)
        await expect(
            conn, RECORD_PAYMENT, "ck_payment_records_amount_positive", **payment_params(engagement, p.finance, 0)
        )
        milestone_payment = payment_params(engagement, p.finance, 5_000_000, milestone=done.milestone)
        await run(conn, RECORD_PAYMENT, **milestone_payment)
        payment = milestone_payment["id"]
        confirm = "UPDATE payment_records SET confirmed_by = :me, confirmed_amount_kes_minor = :amount WHERE id = :id"
        assert await rowcount(conn, confirm, me=p.finance, amount=1, id=payment) == 0  # only the developer's row

        await act(conn, p.developer)
        for assignment in ("amount_kes_minor = 1", "confirmed_at = now()", "paid_on = paid_on", "reference = 'X'"):
            await expect(
                conn, f"UPDATE payment_records SET {assignment} WHERE id = :id", "permission denied", id=payment
            )
        await expect(conn, confirm, "the engagement's developer confirms", me=p.finance, amount=1, id=payment)
        await run(conn, confirm, me=p.developer, amount=4_900_000, id=payment)  # the amount received may differ
        confirmed = (
            await conn.execute(
                sa.text(
                    "SELECT confirmed_at > now() - interval '1 minute' AS timed, confirmed_amount_kes_minor"
                    " FROM payment_records WHERE id = :id"
                ),
                {"id": payment},
            )
        ).one()
        assert tuple(confirmed) == (True, 4_900_000)
        await expect(conn, confirm, "confirmed once", me=p.developer, amount=5_000_000, id=payment)
        await expect(conn, "DELETE FROM payment_records WHERE id = :id", "permission denied", id=payment)
        await as_owner(conn)  # the triggers hold for every role
        await expect(
            conn, "UPDATE payment_records SET amount_kes_minor = 1 WHERE id = :id", "confirmed once", id=payment
        )
        await expect(conn, "DELETE FROM payment_records WHERE id = :id", "append-only", id=payment)
        unconfirmed = payment_params(engagement, p.finance, 700)
        await run(conn, RECORD_PAYMENT, **unconfirmed)
        await expect(
            conn,
            "UPDATE payment_records SET amount_kes_minor = 1 WHERE id = :id",
            "only the developer",
            id=unconfirmed["id"],
        )
        await expect(
            conn, confirm, "the engagement's developer confirms", me=p.finance, amount=700, id=unconfirmed["id"]
        )
        await expect(
            conn,
            RECORD_PAYMENT.replace("recorded_by)", "recorded_by, confirmed_by, confirmed_amount_kes_minor)").replace(
                ":by)", ":by, :by, 1)"
            ),
            "recorded unconfirmed",
            **payment_params(engagement, p.finance, 100),
        )


async def test_a_declined_or_expired_engagement_needs_its_reason(owner_engine: AsyncEngine) -> None:
    """Revision 0002's CHECK let a NULL end_reason through (NULL IN (...) is NULL); revision 0003 replaces it with a
    NULL-safe one, so the table itself refuses DECLINED or EXPIRED without its reason code, for every role; a reason
    on any other state stays refused, and a terminal state without a reason code (WITHDRAWN) is fine."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        definition = await run(
            conn,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_engagements_end_reason_matches_state'",
        )
        assert definition.startswith("CHECK (COALESCE(")
        params = {
            "id": uuid7(),
            "p": p.proposal,
            "org": p.other_org,
            "dev": p.developer,
            "v": p.version,
            "origin": "tagged",
        }
        for state in ("DECLINED", "EXPIRED"):
            await expect(conn, ENGAGE, "ck_engagements_end_reason_matches_state", **params | {"state": state})
        with_reason = ENGAGE.replace("origin, state)", "origin, state, end_reason)").replace(
            "CAST(:state AS engagement_state))", "CAST(:state AS engagement_state), 'BUDGET')"
        )
        await expect(conn, with_reason, "ck_engagements_end_reason_matches_state", **params | {"state": "SUBMITTED"})
        await expect(conn, with_reason, "ck_engagements_end_reason_matches_state", **params | {"state": "EXPIRED"})
        await run(conn, ENGAGE, **params | {"state": "WITHDRAWN"})
        assert await run(conn, "SELECT ended_at IS NOT NULL FROM engagements WHERE id = :id", id=params["id"]) is True
        await run(conn, with_reason, **params | {"id": uuid7(), "org": p.org, "state": "DECLINED"})


async def test_demo_account_is_the_owners_to_set(owner_engine: AsyncEngine) -> None:
    """D-37: whether an account is seeded demo data (the only data a free LLM provider may receive) is set by the
    owner role (the seed); bridge_app reads it, and neither inserts nor updates it."""
    async with as_app(owner_engine) as conn:
        await act(conn, None)
        user_id = uuid7()
        insert = "INSERT INTO users (id, email, display_name, demo_account) VALUES (:id, :email, 'Demo', :demo)"
        for demo in (True, False):  # even the default value may not be named
            await expect(conn, insert, "permission denied", id=user_id, email=f"{uuid4().hex}@example.test", demo=demo)
        session = AsyncSession(bind=conn)
        user = User(email=f"{uuid4().hex}@example.test", display_name="Signed up")
        session.add(user)
        await session.flush()  # the ORM leaves demo_account out and reads it back
        assert user.demo_account is False
        await session.close()
        await act(conn, user.id)
        await expect(conn, "UPDATE users SET demo_account = true WHERE id = :id", "permission denied", id=user.id)
        await as_owner(conn)
        await run(conn, "UPDATE users SET demo_account = true WHERE id = :id", id=user.id)
        await act(conn, user.id)
        assert await run(conn, "SELECT demo_account FROM users WHERE id = :id", id=user.id) is True


async def test_the_test_clock_moves_forward_only_where_the_owner_enabled_it(owner_engine: AsyncEngine) -> None:
    """The shared dev/test clock: disabled (the migration's row) it refuses every move and app_clock_now() is the
    database clock; enabled by the owner it moves only forward (at most 366 days) and every tracker time follows it;
    bridge_app reads the row and changes it only through app_set_test_clock()."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await as_owner(conn)
        await run(
            conn, "UPDATE test_clock SET enabled = false, clock_offset = interval '0'"
        )  # as the migration left it
        await act(conn, p.developer)
        skew = "SELECT app_clock_now() - clock_timestamp()"
        assert abs(await run(conn, skew)) < timedelta(seconds=5)
        await expect(conn, "SELECT app_set_test_clock(interval '1 day')", "not enabled")
        for sql in (
            "UPDATE test_clock SET clock_offset = interval '1 day'",
            "UPDATE test_clock SET enabled = true",
            "INSERT INTO test_clock (singleton) VALUES (true)",
            "DELETE FROM test_clock",
        ):
            await expect(conn, sql, "permission denied")

        await as_owner(conn)
        await run(conn, "UPDATE test_clock SET enabled = true")  # python -m bridge.seed, outside production
        await act(conn, p.developer)
        moved = await run(conn, "SELECT app_set_test_clock(interval '10 days')")
        assert abs(moved - (datetime.now(UTC) + timedelta(days=10))) < timedelta(minutes=1)
        assert await run(conn, "SELECT count(*) FROM test_clock WHERE updated_by = :u", u=p.developer) == 1
        await expect(conn, "SELECT app_set_test_clock(interval '9 days')", "only moves forward")
        await expect(conn, "SELECT app_set_test_clock(NULL)", "only moves forward")
        await expect(conn, "SELECT app_set_test_clock(interval '367 days')", "ck_test_clock_clock_offset")
        engagement = await engage(conn, p)  # every tracker time follows the clock
        times = await conn.execute(
            sa.text(
                "SELECT e.stage_entered_at - clock_timestamp() AS entered, v.created_at - clock_timestamp() AS event"
                " FROM engagements e JOIN engagement_events v ON v.engagement_id = e.id WHERE e.id = :e"
            ),
            {"e": engagement},
        )
        for offset in times.one():
            assert timedelta(days=10) - timedelta(minutes=1) < offset < timedelta(days=10) + timedelta(minutes=1)
        await act(conn, p.reviewer, p.org)
        await append(conn, engagement, p.reviewer, "reviewer", "start_review", "SUBMITTED", "UNDER_REVIEW")
        assert await state_of(conn, engagement) == "UNDER_REVIEW"
        assert await chain.verify_chain(conn, engagement) == []


# --- Review P1 (MAJOR 1, 4; MINOR 5, 6, 7) --------------------------------------------------------------------------


async def refusal(conn: AsyncConnection, sql: str, **params: object) -> str:
    """The SQLSTATE and primary message of ``sql``'s refusal (it must fail), from a savepoint."""
    savepoint = await conn.begin_nested()
    try:
        await conn.execute(sa.text(sql), params)
    except DBAPIError as exc:
        await savepoint.rollback()
        return f"{exc.orig.sqlstate} {exc.orig.diag.message_primary}"  # type: ignore[union-attr]
    await savepoint.rollback()
    raise AssertionError(f"not refused: {sql}")


async def test_an_outsider_learns_nothing_from_a_refused_write(owner_engine: AsyncEngine) -> None:
    """MAJOR 1: before any trigger reads or reports anything about an engagement, a writer who cannot see it (another
    developer, another organisation's member, a forged org context, no user) gets one refusal, the same as for an
    engagement that does not exist: a stale or current state, a wrong stage, a wrong hash, an agreement or milestone
    of it, a payment."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "AGREEMENT_SIGNING")
        assert done.agreement is not None
        missing = uuid7()
        seen: set[str] = set()
        for outsider, org in ((p.outsider, None), (p.other_member, p.other_org), (p.other_member, p.org), (None, None)):
            await act(conn, outsider, org)
            for target in (engagement, missing):
                attempts = (
                    (APPEND, event_params(target, outsider, "developer", "note", "NEGOTIATION", "NEGOTIATION")),
                    (
                        APPEND,
                        event_params(target, outsider, "developer", "sign", "AGREEMENT_SIGNING", "IN_IMPLEMENTATION"),
                    ),
                    (ENDORSE, endorse_params(target, "SUBMITTED", "developer", outsider, "developer")),
                    (ENDORSE, endorse_params(target, "AGREEMENT_SIGNING", "org", outsider, "signatory", "totp")),
                    (
                        SIGN,
                        sign_params(
                            target,
                            "agreement",
                            done.agreement,
                            CERTIFICATE_SHA256,
                            outsider or p.outsider,
                            "developer",
                            "totp",
                        ),
                    ),
                    (
                        "INSERT INTO milestones (id, agreement_id, engagement_id, seq, deliverable, amount_kes_minor,"
                        " due_date, review_window_bd) VALUES (:id, :a, :e, 9, 'X', 1, '2027-01-01', 5)",
                        {"id": uuid7(), "a": done.agreement, "e": target},
                    ),
                    (
                        "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 9, :by)",
                        {"id": uuid7(), "e": target, "by": outsider or p.outsider},
                    ),
                    (
                        RECORD_PAYMENT,
                        payment_params(target, outsider or p.outsider, 100) | {"paid_on": date(2099, 1, 1)},
                    ),
                )
                for sql, params in attempts:
                    seen.add(await refusal(conn, sql, **params))
        assert len(seen) == 1, seen
        (only,) = seen
        assert only.startswith("42501 ")
        assert "AGREEMENT_SIGNING" not in only


async def test_the_main_path_cannot_be_skipped(owner_engine: AsyncEngine) -> None:
    """MAJOR 4: each main-path state follows only its legal predecessors (the database's backstop of the state
    machine), a side branch resumes only to the state it left, the parties cannot close a dispute, and DELIVERED,
    SIGN_OFF and PAYMENT_FINAL need a signed agreement whatever path led there."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await walk(conn, p, engagement, "UNDER_REVIEW")
        await act(conn, p.signatory, p.org)
        for target in ("DELIVERED", "CLOSED", "IN_IMPLEMENTATION", "NDA_SIGNED", "SUBMITTED", "PAYMENT_FINAL"):
            params = event_params(engagement, p.signatory, "signatory", "skip", "UNDER_REVIEW", target)
            await expect(conn, APPEND, f"{target} cannot follow UNDER_REVIEW", **params)
        # A side branch resumes only to the state it was entered from.
        await append(conn, engagement, p.signatory, "signatory", "hold", "UNDER_REVIEW", "ON_HOLD")
        params = event_params(engagement, p.signatory, "signatory", "resume", "ON_HOLD", "INTEREST_CONFIRMED")
        await expect(conn, APPEND, "resumes to UNDER_REVIEW", **params)
        await append(conn, engagement, p.signatory, "signatory", "resume", "ON_HOLD", "UNDER_REVIEW")
        await append(conn, engagement, p.signatory, "signatory", "dispute", "UNDER_REVIEW", "DISPUTED")
        params = event_params(engagement, p.signatory, "signatory", "close", "DISPUTED", "CLOSED")
        await expect(conn, APPEND, "row-level security", **params)  # a dispute's outcome is not the parties' to write
        await append(conn, engagement, p.signatory, "signatory", "resume", "DISPUTED", "UNDER_REVIEW")
        assert await chain.verify_chain(conn, engagement) == []

        # An engagement inserted by the owner in IN_IMPLEMENTATION (as fixtures may) has no signed agreement: it is
        # neither delivered nor signed off nor paid.
        await as_owner(conn)
        later = uuid7()
        await run(
            conn,
            ENGAGE,
            id=later,
            p=p.proposal,
            org=p.other_org,
            dev=p.developer,
            v=p.version,
            origin="tagged",
            state="IN_IMPLEMENTATION",
        )
        await act(conn, p.developer)
        params = event_params(later, p.developer, "developer", "deliver", "IN_IMPLEMENTATION", "DELIVERED")
        await expect(conn, APPEND, "DELIVERED needs an agreement signed by both parties", **params)


async def test_viewers_write_no_system_events_or_automatic_endorsements(owner_engine: AsyncEngine) -> None:
    """MINOR 5: a system event or an automatic endorsement comes from a job bound to the developer or to an
    organisation member who may act (owner, admin, signatory, reviewer, finance), never to a viewer."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        await act(conn, p.viewer, p.org)
        await expect(
            conn,
            APPEND,
            "row-level security",
            **event_params(engagement, None, "system", "remind", "SUBMITTED", "SUBMITTED"),
        )
        await expect(
            conn,
            ENDORSE,
            "row-level security",
            **endorse_params(engagement, "SUBMITTED", "org", None, "system", "auto"),
        )
        await act(conn, p.finance, p.org)
        await append(conn, engagement, None, "system", "remind", "SUBMITTED", "SUBMITTED")
        await run(conn, ENDORSE, **endorse_params(engagement, "SUBMITTED", "org", None, "system", "auto"))


async def test_nothing_is_written_to_an_engagement_that_ended(owner_engine: AsyncEngine) -> None:
    """MINOR 6: once an engagement is in a terminal state, no endorsement, agreement, milestone or signature is added
    and no agreement or milestone changes."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "NEGOTIATION")
        await append(conn, engagement, p.developer, "developer", "withdraw", "NEGOTIATION", "WITHDRAWN")
        await expect(
            conn,
            ENDORSE,
            "only the stage the engagement is in|row-level security|ended",
            **endorse_params(engagement, "WITHDRAWN", "developer", p.developer, "developer"),
        )
        await expect(
            conn,
            SIGN,
            "row-level security",
            **sign_params(engagement, "mutual_nda", uuid7(), PDF_SHA256, p.developer, "developer", "passkey"),
        )
        await expect(
            conn,
            "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 2, :by)",
            "row-level security",
            id=uuid7(),
            e=engagement,
            by=p.developer,
        )
        await expect(
            conn,
            "INSERT INTO milestones (id, agreement_id, engagement_id, seq, deliverable, amount_kes_minor,"
            " due_date, review_window_bd) VALUES (:id, :a, :e, 2, 'More', 1, '2027-01-01', 5)",
            "row-level security",
            id=uuid7(),
            a=done.agreement,
            e=engagement,
        )
        await expect(
            conn,
            "UPDATE agreements SET ip_terms = 'revenue_share' WHERE id = :a",
            "row-level security",
            a=done.agreement,
        )
        await expect(
            conn, "UPDATE milestones SET deliverable = 'Changed' WHERE id = :m", "row-level security", m=done.milestone
        )


async def test_the_parties_are_two_people(owner_engine: AsyncEngine) -> None:
    """MINOR 7: the developer is never a member of the counterpart organisation, and an agreement or an acceptance
    certificate counts as signed by both parties only when two different people signed it."""
    async with as_app(owner_engine) as conn:
        p = await parties(conn)
        await member(conn, p.other_org, p.developer, "{reviewer}")
        await tag(conn, p.proposal, p.other_org, p.developer)
        await act(conn, p.developer)
        await expect(
            conn,
            ENGAGE,
            "row-level security",
            id=uuid7(),
            p=p.proposal,
            org=p.other_org,
            dev=p.developer,
            v=p.version,
            origin="tagged",
            state="SUBMITTED",
        )
        await act(conn, p.other_member, p.other_org)  # an interest by its signatory in its own member's proposal
        await expect(
            conn,
            ENGAGE,
            "the developer may not be a member",
            id=uuid7(),
            p=p.proposal,
            org=p.other_org,
            dev=p.developer,
            v=p.version,
            origin="org_browse",
            state="ORG_INTEREST",
        )
        await as_owner(conn)
        await expect(
            conn,
            ENGAGE,
            "the developer may not be a member",
            id=uuid7(),
            p=p.proposal,
            org=p.other_org,
            dev=p.developer,
            v=p.version,
            origin="tagged",
            state="SUBMITTED",
        )

        await act(conn, p.developer)
        engagement = await engage(conn, p)
        done = await walk(conn, p, engagement, "AGREEMENT_SIGNING")
        assert done.agreement is not None
        await as_owner(conn)  # one person signing for both sides (only the owner could write it)
        for party in ("developer", "org"):
            await run(
                conn,
                SIGN,
                **sign_params(engagement, "agreement", done.agreement, PDF_SHA256, p.signatory, party, "passkey"),
            )
        await expect(
            conn, "UPDATE agreements SET status = 'signed' WHERE id = :a", "once both parties signed", a=done.agreement
        )
