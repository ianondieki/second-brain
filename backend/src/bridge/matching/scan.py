"""One scout run: the rules, the model's "why", the matches, the cursor and the digest (REQ-SCOUT-02; docs/spec/06 6.8).

The job ``scouts.scan`` (daily and weekly scouts, from ``schedule.scan_after`` EAT) and ``scouts.on_new`` (a
publication) ask ``app_scouts_due`` with no user bound (revision 0005), then run each due scout in a session bound to
its acting member and organisation (``bind_tenant``: one tenant per run, docs/spec/08), so every read and write below
is under that member's RLS and every cache (the match rows) is the organisation's:

1. the scout re-read (gone or paused: skipped), its plan's frequencies re-checked (a frequency the plan lost is
   skipped: ``plan``), and a ``running`` run committed first, so a repeated call finds nothing due;
2. the candidates (``pipeline.candidates``) in the run's window: a first scan covers ``limits.first_run_days`` days
   (Preview's window: the Preview equals the first digest, AC-SCOUT-5); a later one continues from the incremental
   cursor with a one-hour overlap (a publication whose transaction committed after the previous read), and strictly
   after the last proposal read when the previous run hit ``limits.scan_per_run``; ``on_new`` reads its one
   proposal. A proposal is matched once per scout (UNIQUE), so the overlap never matches anything twice;
3. the deterministic score, ``min_fit`` and the top ``limits.matches_per_run``; the model explains the top
   ``limits.model_top_n`` (``rationale.explain``), the rest carry the code's line;
4. in one transaction: the matches (``ON CONFLICT DO NOTHING``), a ``scout_match`` signal for each, the cursor
   (daily and weekly runs), and the run completed with its counts. Any failure rolls the step back and marks the run
   ``failed`` with the code ``scan_failed`` (a failed run may be retried the same day or week);
5. the digest (``digest.send``) of the scout's undigested matches, to its re-checked recipients.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from bridge.billing.entitlements import for_subject
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.engagements.calendar import NAIROBI
from bridge.ids import uuid7
from bridge.llm.client import LLMClient
from bridge.llm.types import CallContext
from bridge.logging import get_logger
from bridge.matching import digest
from bridge.matching.config import Weights
from bridge.matching.models import AgentMatch, AgentRun, ScoutAgent
from bridge.matching.pipeline import Filters, Page, Scored, Window, candidates, final_score, score, select_top
from bridge.matching.rationale import Explanation, Profile, by_code, explain
from bridge.models.enums import ScoutFrequency
from bridge.notifications.email import EmailProvider
from bridge.tenancy import signals

OVERLAP: Final = timedelta(hours=1)
PERIODIC: Final = (ScoutFrequency.DAILY, ScoutFrequency.WEEKLY)
FAILED_CODE: Final = "scan_failed"
_DUE = text(
    "SELECT scout_id, org_id, act_as_user_id FROM app_scouts_due(:now, CAST(:trigger AS scout_frequency), :proposal)"
)
_CLOCK = text("SELECT app_clock_now()")
_DB_NOW = text("SELECT now()")  # proposals.published_at is the database's own clock, not the test clock
_FINISH = text(
    "UPDATE agent_runs SET status = CAST(:status AS agent_run_status), finished_at = app_clock_now(),"
    " scanned_count = :scanned, matched_count = :matched, error_code = :error WHERE id = :id"
)
Status = Literal["completed", "failed", "skipped"]
log = get_logger(__name__)


@dataclass(frozen=True)
class ScanDeps:
    """What a scan needs. ``llm`` gives the client of a session bound to the scout's tenant (None: no model)."""

    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    email: EmailProvider
    weights: Weights
    llm: Callable[[AsyncSession], LLMClient | None] = field(default=lambda _db: None)


@dataclass(frozen=True, slots=True)
class Due:
    scout_id: UUID
    org_id: UUID
    act_as_user_id: UUID


@dataclass(frozen=True, slots=True)
class Outcome:
    """One scout's result: ``skipped`` (with the reason), ``failed`` or ``completed`` with its counts."""

    scout_id: UUID
    org_id: UUID
    status: Status
    run_id: UUID | None = None
    scanned: int = 0
    matched: int = 0
    reason: str | None = None
    digest: digest.Sent | None = None


async def clock_now(factory: async_sessionmaker[AsyncSession]) -> datetime:
    async with factory() as db:
        now: datetime = (await db.execute(_CLOCK)).scalar_one()
        return now


async def due(
    factory: async_sessionmaker[AsyncSession], now: datetime, trigger: ScoutFrequency, proposal_id: UUID | None = None
) -> list[Due]:
    """The scouts due now (``app_scouts_due``, called with no user bound: the job's own session)."""
    async with factory() as db:
        rows = await db.execute(_DUE, {"now": now, "trigger": trigger.value, "proposal": proposal_id})
        return [Due(r.scout_id, r.org_id, r.act_as_user_id) for r in rows.all()]


def filters_of(scout: ScoutAgent) -> Filters:
    return Filters(
        org_id=scout.org_id,
        niches=tuple(scout.niches),
        counties=tuple(scout.counties),
        include_keywords=tuple(scout.include_keywords),
        exclude_keywords=tuple(scout.exclude_keywords),
        maturity=tuple(scout.maturity),
        min_fit=scout.min_fit,
        scout_id=scout.id,
    )


def window_of(scout: ScoutAgent, until: datetime, weights: Weights, proposal_id: UUID | None) -> Window:
    if proposal_id is not None:
        return Window(until=until, proposal_id=proposal_id)
    if scout.cursor_at is None:
        return Window(until=until, since=until - timedelta(days=weights.first_run_days))
    if scout.cursor_proposal_id is not None:  # the previous run hit its limit: continue strictly after it
        return Window(until=until, after=(scout.cursor_at, scout.cursor_proposal_id))
    return Window(until=until, since=scout.cursor_at - OVERLAP)


async def profile_of(db: AsyncSession, scout: ScoutAgent) -> Profile:
    parent = aliased(Niche)
    rows = await db.execute(
        select(Niche.name_en, parent.name_en)
        .outerjoin(parent, parent.id == Niche.parent_id)
        .where(Niche.id.in_(list(scout.niches)))
        .order_by(Niche.name_en)
    )
    labels = tuple(niche_label(name, parent_name) for name, parent_name in rows.all())
    return Profile(owner_id=scout.created_by, niche_labels=labels, include_keywords=tuple(scout.include_keywords))


async def scan(deps: ScanDeps, found: Due, trigger: ScoutFrequency, *, proposal_id: UUID | None = None) -> Outcome:
    """Run one due scout (see the module docstring)."""
    async with deps.factory() as db:
        await bind_tenant(db, user_id=found.act_as_user_id, org_id=found.org_id)
        scout = await db.get(ScoutAgent, found.scout_id)
        if scout is None or scout.org_id != found.org_id:
            return Outcome(found.scout_id, found.org_id, "skipped", reason="not_found")
        if scout.paused_at is not None:
            return Outcome(found.scout_id, found.org_id, "skipped", reason="paused")
        plan = await for_subject(db, deps.settings, org_id=found.org_id)
        allowed = plan.limits.get("scout_frequencies") or []
        if scout.frequency.value not in allowed:
            log.info("scouts.skipped", scout_id=str(scout.id), reason="plan")
            return Outcome(found.scout_id, found.org_id, "skipped", reason="plan")
        until: datetime = (await db.execute(_DB_NOW)).scalar_one()
        window = window_of(scout, until, deps.weights, proposal_id)
        start = window.since or (window.after[0] if window.after else None)
        run = AgentRun(
            id=uuid7(),
            scout_id=scout.id,
            org_id=scout.org_id,
            trigger=trigger,
            window_start=start if proposal_id is None else None,
            window_end=until,
        )
        db.add(run)
        await db.commit()
        run_id, size = run.id, deps.weights.digest_size(plan.limits.get("scout_digest"))
        try:
            scanned, matched = await _work(deps, db, scout, run_id, window, found.act_as_user_id)
        except Exception as exc:
            await db.rollback()
            await db.execute(
                _FINISH, {"status": "failed", "scanned": 0, "matched": 0, "error": FAILED_CODE, "id": run_id}
            )
            await db.commit()
            log.error(
                "scouts.scan_failed", scout_id=str(found.scout_id), run_id=str(run_id), error_type=type(exc).__name__
            )
            return Outcome(found.scout_id, found.org_id, "failed", run_id=run_id, reason=FAILED_CODE)
        recipients = list(scout.recipients)
        sent = await digest.send(
            db,
            deps.factory,
            deps.email,
            deps.settings,
            scout_id=found.scout_id,
            org_id=found.org_id,
            run_id=run_id,
            listed_recipients=recipients,
            size=size,
        )
    log.info("scouts.scanned", scout_id=str(found.scout_id), run_id=str(run_id), scanned=scanned, matched=matched)
    return Outcome(found.scout_id, found.org_id, "completed", run_id, scanned, matched, digest=sent)


async def _work(
    deps: ScanDeps, db: AsyncSession, scout: ScoutAgent, run_id: UUID, window: Window, act_as: UUID
) -> tuple[int, int]:
    weights = deps.weights
    filters = filters_of(scout)
    page = await candidates(db, filters, window, limit=weights.scan_per_run)
    chosen = select_top([score(c, filters, weights) for c in page.items], filters.min_fit, weights.matches_per_run)
    profile = await profile_of(db, scout)
    client = deps.llm(db) if chosen and weights.model_top_n else None
    matched = 0
    for index, s in enumerate(chosen):
        if index < weights.model_top_n:
            ctx = CallContext(org_id=scout.org_id, user_id=act_as, trace_id=f"scout-{run_id.hex[-12:]}-{index}")
            why = await explain(client, profile, s, ctx=ctx)
        else:
            why = by_code(s, "beyond_top_n")
        matched += await _insert_match(db, deps.settings, scout, s, why, weights)
    if window.proposal_id is None:
        _advance(scout, page, window)
    await db.execute(
        _FINISH, {"status": "completed", "scanned": len(page.items), "matched": matched, "error": None, "id": run_id}
    )
    await db.commit()
    return len(page.items), matched


def _advance(scout: ScoutAgent, page: Page, window: Window) -> None:
    """The cursor after a periodic run: its last proposal when it hit its limit, else the window's end."""
    if page.full and page.last is not None:
        scout.cursor_at, scout.cursor_proposal_id = page.last
    else:
        scout.cursor_at, scout.cursor_proposal_id = window.until, None


async def _insert_match(
    db: AsyncSession, settings: Settings, scout: ScoutAgent, s: Scored, why: Explanation, weights: Weights
) -> int:
    c = s.candidate
    final = final_score(s.score, why.model_fit, weights)
    breakdown = s.breakdown() | {
        "final": final,
        "model_fit": why.model_fit,
        "why_source": why.source,
        "why_reason": why.reason,
    }
    inserted = await db.execute(
        insert(AgentMatch)
        .values(
            id=uuid7(),
            scout_id=scout.id,
            org_id=scout.org_id,
            proposal_id=c.proposal_id,
            version_id=c.version_id,
            niche_id=c.niche_id,
            score=final,
            rule_breakdown=breakdown,
            rationale=why.text,
            rationale_demo_fallback=why.demo_fallback,
            injection_suspected=why.injection_suspected,
        )
        .on_conflict_do_nothing(index_elements=["scout_id", "proposal_id"])
        .returning(AgentMatch.id)
    )
    if inserted.scalar_one_or_none() is None:
        return 0
    await signals.record(db, settings, item_id=c.proposal_id, kind=signals.SCOUT_MATCH, org_id=scout.org_id)
    return 1


async def run_periodic(deps: ScanDeps, *, now: datetime | None = None, force: bool = False) -> list[Outcome]:
    """One pass of ``scouts.scan``: every daily and weekly scout due at ``now`` (the shared clock), from
    ``schedule.scan_after`` EAT unless ``force`` (``python -m bridge.matching run --now``, dev and test only)."""
    now = now or await clock_now(deps.factory)
    if not force and now.astimezone(NAIROBI).time() < deps.weights.scan_after:
        return []
    outcomes = []
    for trigger in PERIODIC:
        for found in await due(deps.factory, now, trigger):
            outcomes.append(await _safely(deps, found, trigger))
    return outcomes


async def run_on_new(deps: ScanDeps, proposal_id: UUID, *, now: datetime | None = None) -> list[Outcome]:
    """``scouts.on_new``: every on_new scout due for a publication (published, clear, not matched yet)."""
    now = now or await clock_now(deps.factory)
    found = await due(deps.factory, now, ScoutFrequency.ON_NEW, proposal_id)
    return [await _safely(deps, d, ScoutFrequency.ON_NEW, proposal_id) for d in found]


async def _safely(deps: ScanDeps, found: Due, trigger: ScoutFrequency, proposal_id: UUID | None = None) -> Outcome:
    """One scout never stops the others (its failure is logged; the next pass retries a failed run)."""
    try:
        return await scan(deps, found, trigger, proposal_id=proposal_id)
    except Exception as exc:
        log.error("scouts.scout_failed", scout_id=str(found.scout_id), error_type=type(exc).__name__)
        return Outcome(found.scout_id, found.org_id, "failed", reason="error")
