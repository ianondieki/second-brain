"""A research run from start to candidates (REQ-RES-01; docs/spec/06 6.5; PLAN §8 P11).

``start_run`` inserts a ``research_runs`` row as the signed-in staff admin (``started_by``; the table's RLS admits
staff admins only) for one niche, nationally (Release 1 runs at national level; county runs are Release 2), refusing
a second running run of the same niche and country. The admin API then queues ``research.run``
(``bridge.problems.research.tasks``).

``execute_run`` is the job's body, on a session bound to the run's starter (so every write is that staff admin's, and
``app_create_research_candidate`` accepts only their own running run). In order:

1. The run, read ``FOR UPDATE`` (another worker's copy of the job waits and then finds it finished); a run that is not
   running is left alone (the job is idempotent); a run older than ``stale_run_minutes`` is stopped (``stale``), since
   a newer run of its niche may exist by then (``start_run`` no longer counts it).
2. The niche's saved excerpts that are not archived on the shared clock's Nairobi date, freshest first, at most
   ``max_excerpts``; fewer than ``min_excerpts`` stops the run (``not_enough_excerpts``).
3. The caps (AC-RES-3; ``policy.yaml``): no search and no fetch ever happens here, so both stay 0 (the
   ``research_runs`` CHECK is the backstop); the input's token estimate (``ai/models.yaml`` characters per token) over
   ``max_input_tokens`` stops the run (``input_token_cap``) before any call.
4. One ``research_synthesis`` call through ``LLMClient`` (budget checks before it, one ``llm_calls`` row per
   attempt, the D-37 demo-data rule on free slots: the staff admin must be a demo account and the excerpts are public
   fields). ``CallContext`` carries the starter, never tenant data. A typed LLM error fails the run with the error's
   code; a caller's mistake (``LLMConfigError``) propagates.
5. A demo fallback (``Result.demo_fallback``) completes the run flagged ``demo_fallback`` with no card: a placeholder
   is never a draft. ``injection_suspected`` stops the run (``injection_suspected``) with every draft discarded.
6. Each draft through ``checks.check_draft``; drafts over ``max_cards_per_run`` are discarded. A kept draft becomes a
   candidate through ``app_create_research_candidate`` (in a savepoint: a database refusal discards that draft only)
   with its cited sources exactly as saved (URL, publisher, type, dates, verbatim quote, ``excerpt_ref``) and the
   county the draft names when it is a county of the run's country in the regions table (``county_of``; otherwise
   the card is nationwide).
7. The run is finished: completed (or stopped, failed), counts, input tokens and cost from the call.

The caller commits. ``origin=SEEDED_EXAMPLE`` is the demo seed's path only (dev and test): the same checks on a fixed
answer written in code, and every source's ``excerpt_ref`` is ``example:<id>``, which the problem API reads to label
the card a seeded example rather than an AI draft (``bridge.problems.service``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.db import tenant_of
from bridge.directory.models import Niche
from bridge.ids import uuid7
from bridge.llm import registry as registry_module
from bridge.llm.client import LLMClient
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext, Instruction, Message, Result
from bridge.logging import get_logger
from bridge.models.enums import ResearchRunStatus
from bridge.problems.models import ResearchRun
from bridge.problems.research import checks, synthesis
from bridge.problems.research.policy import ResearchPolicy, get_research_policy
from bridge.problems.research.sources import Catalogue, Excerpt

NAIROBI: Final = ZoneInfo("Africa/Nairobi")
EXAMPLE_REF_PREFIX: Final = "example:"
SEED_ENVS: Final = frozenset({"dev", "test"})
_CLOCK: Final = text("SELECT app_clock_now()")
_DB_NOW: Final = text("SELECT now()")  # created_at's own clock (the run's start), for the stale-run rule
_RUN_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_CREATE: Final = text(
    "SELECT app_create_research_candidate(:run, :title, :statement, :group, :county, CAST(:confidence AS numeric),"
    " CAST(:named AS text[]), CAST(:sources AS jsonb))"
)
# A draft's county: a code of this shape, then a county of the run's country in the regions table (else dropped).
_COUNTY_SHAPE: Final = re.compile(r"[A-Z]{2}-[A-Za-z0-9]{1,5}")
_KNOWN_COUNTY: Final = text(
    "SELECT code FROM regions WHERE code = :code AND kind = 'county' AND parent_code = :country"
)
_REFUSALS: Final = frozenset({"23514", "22001", "22007", "22008", "22P02", "23502"})  # the definer's data refusals
log = get_logger(__name__)


class CardOrigin(StrEnum):
    LIVE = "live"
    SEEDED_EXAMPLE = "seeded_example"  # the demo seed's fixed answer (dev and test only)


class RunRefused(Exception):
    """A run cannot start: ``code`` is the API's error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: UUID
    status: ResearchRunStatus
    stop_reason: str | None
    demo_fallback: bool
    candidates: tuple[UUID, ...] = ()
    discarded: tuple[str, ...] = field(default=())  # one reason per discarded draft


def nairobi_date(moment: datetime) -> date:
    return moment.astimezone(NAIROBI).date()


async def clock_now(db: AsyncSession) -> datetime:
    now: datetime = (await db.execute(_CLOCK)).scalar_one()
    return now


# ---------------------------------------------------------------------------------------------------------- start


async def start_run(
    db: AsyncSession,
    *,
    user_id: UUID,
    niche_slug: str,
    country: str,
    catalogue: Catalogue,
    policy: ResearchPolicy | None = None,
) -> ResearchRun:
    """A running run of ``niche_slug`` in ``country`` started by ``user_id`` (the caller's transaction). A running run
    of the niche younger than ``stale_run_minutes`` refuses it (``run_in_progress``); an older one (its job lost, or
    its starter no longer a staff admin, so it can never finish) no longer blocks the niche."""
    policy = policy or get_research_policy()
    if country not in catalogue.allowlists or niche_slug not in catalogue.niches(country):
        raise RunRefused("no_saved_excerpts")
    niche_id = await db.scalar(select(Niche.id).where(Niche.slug == niche_slug))
    if niche_id is None:
        raise RunRefused("unknown_niche")
    # Two admins starting the same niche at once: the second waits here and then counts the first's committed run.
    await db.execute(_RUN_LOCK, {"key": f"research-run:{niche_id}:{country}"})
    running = await db.scalar(
        select(func.count())
        .select_from(ResearchRun)
        .where(
            ResearchRun.niche_id == niche_id,
            ResearchRun.country == country,
            ResearchRun.county_code.is_(None),
            ResearchRun.status == ResearchRunStatus.RUNNING,
            ResearchRun.created_at > func.now() - timedelta(minutes=policy.stale_run_minutes),
        )
    )
    if running:
        raise RunRefused("run_in_progress")
    run = ResearchRun(id=uuid7(), niche_id=niche_id, country=country, started_by=user_id)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


# -------------------------------------------------------------------------------------------------------- execute


def _source(excerpt: Excerpt, origin: CardOrigin) -> dict[str, str]:
    ref = f"{EXAMPLE_REF_PREFIX}{excerpt.id}" if origin is CardOrigin.SEEDED_EXAMPLE else excerpt.id
    return {
        "url": excerpt.url,
        "publisher": excerpt.publisher,
        "source_type": excerpt.source_type,
        "published_date": excerpt.published_date.isoformat(),
        "retrieved_at": excerpt.retrieved_at.isoformat(),
        "quote": excerpt.quote,
        "excerpt_ref": ref,
    }


async def _finish(
    db: AsyncSession,
    run: ResearchRun,
    status: ResearchRunStatus,
    *,
    stop_reason: str | None = None,
    candidates: Sequence[UUID] = (),
    discarded: Sequence[str] = (),
    result: Result[synthesis.ResearchSynthesis] | None = None,
) -> RunOutcome:
    usage = result.usage if result is not None else None
    run.status = status
    run.stop_reason = stop_reason
    run.finished_at = await clock_now(db)
    run.candidates = len(candidates)
    run.discarded = len(discarded)
    run.demo_fallback = result is not None and result.demo_fallback
    if usage is not None:
        run.input_tokens = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
        run.cost_usd = result.cost_usd if result is not None else Decimal(0)
    await db.flush()
    outcome = RunOutcome(run.id, status, stop_reason, run.demo_fallback, tuple(candidates), tuple(discarded))
    log.info(
        "research.run_finished",
        run_id=str(run.id),
        status=status.value,
        stop_reason=stop_reason,
        demo_fallback=run.demo_fallback,
        candidates=len(candidates),
        discarded=list(discarded),
        cost_usd=str(run.cost_usd),
    )
    return outcome


def _estimated_tokens(settings: Settings, messages: Sequence[Message]) -> int:
    per_token = registry_module.load(settings.llm_models_file).budget.chars_per_token
    parts = [part for message in messages for part in message.parts]
    chars = sum(len(part.text if isinstance(part, Instruction) else part.value) for part in parts)
    return -(-chars // per_token)


async def execute_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    client: LLMClient,
    settings: Settings,
    catalogue: Catalogue,
    policy: ResearchPolicy,
    origin: CardOrigin = CardOrigin.LIVE,
) -> RunOutcome | None:
    """Run one research run (see the module docstring); None when it is not a running run of the bound admin's."""
    if origin is CardOrigin.SEEDED_EXAMPLE and settings.app_env not in SEED_ENVS:
        raise LLMConfigError("seeded example cards exist only in dev and test (the demo seed)")
    run = await db.get(ResearchRun, run_id, with_for_update=True, populate_existing=True)
    if run is None or run.status is not ResearchRunStatus.RUNNING or run.started_by != tenant_of(db)[0]:
        return None  # not visible, finished, or another staff admin's (only the starter's session runs it)
    started: datetime = (await db.execute(_DB_NOW)).scalar_one()
    if run.created_at < started - timedelta(minutes=policy.stale_run_minutes):
        # Its job ran too late (a stopped worker): a newer run may already exist, so this one never runs.
        return await _finish(db, run, ResearchRunStatus.STOPPED, stop_reason="stale")
    niche = await db.scalar(select(Niche.slug).where(Niche.id == run.niche_id))
    allowlist = catalogue.allowlists.get(run.country)
    if niche is None or allowlist is None:
        return await _finish(db, run, ResearchRunStatus.STOPPED, stop_reason="no_saved_excerpts")
    as_of = nairobi_date(await clock_now(db))
    excerpts = catalogue.usable(str(niche), run.country, as_of, policy)
    if len(excerpts) < policy.min_excerpts:
        return await _finish(db, run, ResearchRunStatus.STOPPED, stop_reason="not_enough_excerpts")
    if run.searches > policy.max_searches or run.fetches > policy.max_fetches:  # never: nothing is fetched here
        return await _finish(db, run, ResearchRunStatus.STOPPED, stop_reason="search_or_fetch_cap")
    messages = synthesis.messages(
        str(niche), excerpts, max_cards=policy.max_cards_per_run, min_support_words=policy.min_support_words
    )
    if _estimated_tokens(settings, messages) > policy.max_input_tokens:
        return await _finish(db, run, ResearchRunStatus.STOPPED, stop_reason="input_token_cap")
    ctx = CallContext(user_id=run.started_by, trace_id=f"research:{run.id.hex}")
    try:
        result = await client.complete(synthesis.TASK, messages, synthesis.ResearchSynthesis, ctx=ctx)
    except LLMConfigError:
        raise
    except LLMError as exc:
        return await _finish(db, run, ResearchRunStatus.FAILED, stop_reason=exc.code)
    if result.demo_fallback:
        return await _finish(db, run, ResearchRunStatus.COMPLETED, result=result)
    drafts = result.parsed.problems
    if result.parsed.injection_suspected:
        reasons = ["injection_suspected"] * len(drafts)
        return await _finish(
            db, run, ResearchRunStatus.STOPPED, stop_reason="injection_suspected", discarded=reasons, result=result
        )
    sent = {e.id: e for e in excerpts}
    created: list[UUID] = []
    discarded = ["over_card_limit"] * max(0, len(drafts) - policy.max_cards_per_run)
    for draft in drafts[: policy.max_cards_per_run]:
        verdict = checks.check_draft(draft.draft(), sent, allowlist, policy, as_of)
        if isinstance(verdict, checks.Discarded):
            discarded.append(verdict.reason)
            continue
        problem_id = await _create(db, run, verdict, origin, await county_of(db, run, draft.county_code))
        if problem_id is None:
            discarded.append("refused_by_database")
        else:
            created.append(problem_id)
    return await _finish(db, run, ResearchRunStatus.COMPLETED, candidates=created, discarded=discarded, result=result)


async def county_of(db: AsyncSession, run: ResearchRun, proposed: str | None) -> str | None:
    """The county a draft names, when it is a county of the run's country in the regions table; None otherwise. The
    code is the model's answer, so it is data: one of an unknown shape never reaches the database, and an unknown or
    foreign code is dropped (the card stays, nationwide), never an error. A county run's cards keep the run's county
    (``app_create_research_candidate``'s rule), so a draft's own county is dropped there too."""
    if proposed is None or run.county_code is not None or not _COUNTY_SHAPE.fullmatch(proposed):
        return None
    known: str | None = await db.scalar(_KNOWN_COUNTY, {"code": proposed, "country": run.country})
    if known is None:
        log.info("research.county_dropped", run_id=str(run.id))
    return known


async def _create(
    db: AsyncSession, run: ResearchRun, card: checks.Accepted, origin: CardOrigin, county: str | None = None
) -> UUID | None:
    params = {
        "run": run.id,
        "title": card.text.title,
        "statement": card.text.statement,
        "group": card.text.affected_group,
        "county": county,
        "confidence": str(card.confidence),
        "named": list(card.text.named_orgs),
        "sources": json.dumps([_source(e, origin) for e in card.sources], ensure_ascii=False),
    }
    try:
        async with db.begin_nested():
            problem_id: UUID = (await db.execute(_CREATE, params)).scalar_one()
    except DBAPIError as exc:
        if str(getattr(exc.orig, "sqlstate", None)) not in _REFUSALS:
            raise
        log.warning("research.candidate_refused", run_id=str(run.id), sqlstate=getattr(exc.orig, "sqlstate", None))
        return None
    return problem_id
