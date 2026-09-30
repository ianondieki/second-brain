"""Scouts API: configure, pause, delete and Preview (REQ-SCOUT-01; docs/spec/06 6.8; AC-SCOUT-5, AC-SCOUT-7, AC-SCOUT-8,
AC-DIR-5/b).

- ``GET /api/orgs/{org_id}/scouts``: any member; the scouts, what the plan allows and the budget band codes.
- ``POST /api/orgs/{org_id}/scouts``: the organisation's owner or admin. 402 (``plan_limit``, the next plan up)
  beyond the plan's ``scout_agents`` or for a frequency the plan lacks (``scout_frequencies``); nothing is created.
- ``GET|PATCH|DELETE /api/orgs/{org_id}/scouts/{id}``: read (any member), change or pause (``paused``), delete (owner
  or admin). Resuming a scout, or changing its frequency, checks the plan again.
- ``POST /api/orgs/{org_id}/scouts/preview``: the owner or admin; the form's matches over the last
  ``limits.first_run_days`` days by the rules alone: no model, no write, nothing queued (pending organisations too).
  For an ``on_new`` scout, which sends new proposals only, ``note`` says what the items are.

A non-member gets 404 (the organisation's existence is not confirmed), a member without the role 403, another
organisation's scout 404. Niches (active ones, so an admin-added niche works without a deploy), counties and the budget
band are checked against the database and ``weights_v1.yaml`` (422); recipients must be active reviewers of the
organisation (422; the database checks it too, and the digest re-checks at send time).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bridge.audit.service import record as audit
from bridge.auth.deps import Db, SettingsDep
from bridge.billing import entitlements
from bridge.config import Settings
from bridge.directory.models import Niche
from bridge.directory.service import niche_label
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.ids import uuid7
from bridge.matching.config import Weights, get_weights
from bridge.matching.models import AgentRun, ScoutAgent
from bridge.matching.pipeline import Filters, Window, candidates, matched_on, score, select_top
from bridge.matching.schemas import (
    BudgetBandOut,
    PreviewItem,
    PreviewOut,
    RunOut,
    ScoutForm,
    ScoutList,
    ScoutOut,
    ScoutPatch,
    ScoutPlanOut,
)
from bridge.models.enums import ScoutFrequency
from bridge.proposals.schemas import NicheOut, TeaserOut
from bridge.tenancy.deps import OrgAdmin, OrgMember

router = APIRouter(tags=["scouts"], responses=ERROR_RESPONSES)
PREFIX: Final = "/api/orgs/{org_id}/scouts"
SCOUT_AGENTS: Final = "scout_agents"
SCOUT_FREQUENCIES: Final = "scout_frequencies"
_NOW = text("SELECT now()")
_COUNTIES = text("SELECT code FROM regions WHERE code = ANY(:codes) AND kind = 'county'")
_REVIEWERS = text(
    "SELECT user_id FROM memberships WHERE org_id = :org AND user_id = ANY(:users) AND status = 'active'"
    " AND roles && CAST('{reviewer}' AS org_role[])"
)


def invalid(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def plan_out(ent: entitlements.Entitlements, weights: Weights) -> ScoutPlanOut:
    return ScoutPlanOut(
        plan=ent.plan_code,
        scout_agents=ent.limit(SCOUT_AGENTS),
        frequencies=[ScoutFrequency(f) for f in ent.limits.get(SCOUT_FREQUENCIES) or []],
        digest_size=weights.digest_size(ent.limits.get("scout_digest")),
    )


def check_frequency(settings: Settings, ent: entitlements.Entitlements, frequency: ScoutFrequency) -> None:
    """402 for a frequency the plan does not include (docs/spec/06 6.8 "frequency ... per plan")."""
    if frequency.value not in (ent.limits.get(SCOUT_FREQUENCIES) or []):
        raise entitlements.PlanLimitExceeded(settings, ent, SCOUT_FREQUENCIES, limit=None, used=None)


async def _active_scouts(db: AsyncSession, org_id: UUID, *, but: UUID | None = None) -> int:
    query = select(func.count()).select_from(ScoutAgent).where(ScoutAgent.org_id == org_id)
    query = query.where(ScoutAgent.paused_at.is_(None))
    if but is not None:
        query = query.where(ScoutAgent.id != but)
    return int(await db.scalar(query) or 0)


async def check_form(
    db: AsyncSession,
    org_id: UUID,
    weights: Weights,
    *,
    niches: list[UUID] | None,
    counties: list[str] | None,
    budget_band: str | None,
    recipients: list[UUID] | None,
) -> None:
    """422 for an unknown or inactive niche, an unknown county, an unknown budget band or a recipient who is not an
    active reviewer of the organisation."""
    if niches is not None:
        found = set((await db.execute(select(Niche.id).where(Niche.id.in_(niches), Niche.active))).scalars())
        if found != set(niches):
            raise invalid("unknown_niche", "Choose niches from the list.")
    if counties:
        known = set((await db.execute(_COUNTIES, {"codes": counties})).scalars())
        if known != set(counties):
            raise invalid("unknown_county", "Choose counties from the list.")
    if budget_band is not None and weights.band(budget_band) is None:
        raise invalid("unknown_budget_band", "Choose a budget band from the list.")
    if recipients:
        reviewers = set((await db.execute(_REVIEWERS, {"org": org_id, "users": recipients})).scalars())
        if reviewers != set(recipients):
            raise invalid("invalid_recipients", "Digest recipients must be reviewers of your organisation.")


async def _niches(db: AsyncSession, ids: Iterable[UUID]) -> dict[UUID, NicheOut]:
    parent = aliased(Niche)
    rows = await db.execute(
        select(Niche.id, Niche.slug, Niche.name_en, parent.name_en)
        .outerjoin(parent, parent.id == Niche.parent_id)
        .where(Niche.id.in_(set(ids)))
    )
    return {r[0]: NicheOut(id=r[0], slug=r[1], label=niche_label(r[2], r[3])) for r in rows.all()}


async def scout_out(db: AsyncSession, scout: ScoutAgent) -> ScoutOut:
    [out] = await scouts_out(db, [scout])
    return out


async def scouts_out(db: AsyncSession, scouts: Sequence[ScoutAgent]) -> list[ScoutOut]:
    """Each scout with its niches and its last run, one query for all their runs and one for all their niches
    (P16-E1: the list sends as many statements for ten scouts as for one)."""
    runs = await db.execute(
        select(AgentRun)
        .where(AgentRun.scout_id.in_([s.id for s in scouts]))
        .order_by(AgentRun.scout_id, AgentRun.started_at.desc())
        .distinct(AgentRun.scout_id)
    )
    last = {run.scout_id: run for run in runs.scalars()}
    niches = await _niches(db, (n for s in scouts for n in s.niches))
    return [_scout_out(s, [niches[n] for n in s.niches if n in niches], last.get(s.id)) for s in scouts]


def _scout_out(scout: ScoutAgent, niches: list[NicheOut], run: AgentRun | None) -> ScoutOut:
    return ScoutOut(
        id=scout.id,
        org_id=scout.org_id,
        niches=niches,
        counties=list(scout.counties),
        include_keywords=list(scout.include_keywords),
        exclude_keywords=list(scout.exclude_keywords),
        maturity=list(scout.maturity),
        budget_band=scout.budget_band,
        min_fit=scout.min_fit,
        frequency=scout.frequency,
        language=scout.language,
        recipients=list(scout.recipients),
        paused=scout.paused_at is not None,
        paused_at=scout.paused_at,
        created_by=scout.created_by,
        created_at=scout.created_at,
        updated_at=scout.updated_at,
        last_run=None if run is None else RunOut.model_validate(run, from_attributes=True),
    )


async def _own_scout(db: AsyncSession, org_id: UUID, scout_id: UUID) -> ScoutAgent:
    scout = await db.scalar(select(ScoutAgent).where(ScoutAgent.id == scout_id, ScoutAgent.org_id == org_id))
    if scout is None:
        raise not_found("No scout of your organisation has this id.")
    return scout


def _db_refusal(exc: DBAPIError) -> ApiError | None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23514":  # a CHECK or the recipients trigger: the form was checked first, so a race or a bug
        return invalid("invalid_scout", "These settings are not valid for a scout.")
    if sqlstate == "42501":
        return ApiError(403, "forbidden", "Only an owner or admin of the organisation configures scouts.")
    return None


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        mapped = _db_refusal(exc)
        if mapped is None:
            raise
        raise mapped from exc


@router.get(PREFIX)
async def list_scouts(org: OrgMember, db: Db, settings: SettingsDep) -> ScoutList:
    """The organisation's scouts, what its plan allows and the budget band codes."""
    weights = get_weights()
    scouts = (
        (
            await db.execute(
                select(ScoutAgent).where(ScoutAgent.org_id == org.org_id).order_by(ScoutAgent.created_at, ScoutAgent.id)
            )
        )
        .scalars()
        .all()
    )
    ent = await entitlements.for_subject(db, settings, org_id=org.org_id)
    return ScoutList(
        items=await scouts_out(db, scouts),
        plan=plan_out(ent, weights),
        budget_bands=[BudgetBandOut(code=b.code, label=b.label) for b in weights.budget_bands],
    )


@router.post(PREFIX, status_code=201)
async def create_scout(body: ScoutForm, org: OrgAdmin, db: Db, settings: SettingsDep) -> ScoutOut:
    """A new scout (402 beyond the plan's scouts or for a frequency it lacks; 422 for an invalid form)."""
    weights = get_weights()
    ent = await entitlements.for_subject(db, settings, org_id=org.org_id)
    used = int(
        await db.scalar(select(func.count()).select_from(ScoutAgent).where(ScoutAgent.org_id == org.org_id)) or 0
    )
    entitlements.check_count(settings, ent, SCOUT_AGENTS, used=used)
    check_frequency(settings, ent, body.frequency)
    await check_form(
        db,
        org.org_id,
        weights,
        niches=body.niches,
        counties=body.counties,
        budget_band=body.budget_band,
        recipients=body.recipients,
    )
    scout = ScoutAgent(id=uuid7(), org_id=org.org_id, created_by=org.live.user.id, **body.model_dump())
    db.add(scout)
    await audit(
        db,
        "scout.created",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="scout",
        subject_id=scout.id,
        payload={"frequency": body.frequency.value, "niches": [str(n) for n in body.niches]},
    )
    await _commit(db)
    await db.refresh(scout)
    return await scout_out(db, scout)


@router.post(f"{PREFIX}/preview")
async def preview(body: ScoutForm, org: OrgAdmin, db: Db, settings: SettingsDep) -> PreviewOut:
    """The first digest this form would send: the last 30 days, the rules only (no model, nothing saved)."""
    weights = get_weights()
    await check_form(
        db,
        org.org_id,
        weights,
        niches=body.niches,
        counties=body.counties,
        budget_band=body.budget_band,
        recipients=None,
    )
    ent = await entitlements.for_subject(db, settings, org_id=org.org_id)
    size = weights.digest_size(ent.limits.get("scout_digest"))
    until: datetime = (await db.execute(_NOW)).scalar_one()
    filters = Filters(
        org_id=org.org_id,
        niches=tuple(body.niches),
        counties=tuple(body.counties),
        include_keywords=tuple(body.include_keywords),
        exclude_keywords=tuple(body.exclude_keywords),
        maturity=tuple(body.maturity),
        min_fit=body.min_fit,
    )
    window = Window(until=until, since=until - timedelta(days=weights.first_run_days))
    page = await candidates(db, filters, window, limit=weights.scan_per_run)
    chosen = select_top([score(c, filters, weights) for c in page.items], body.min_fit, weights.matches_per_run)
    await db.rollback()  # Preview writes nothing
    items = []
    for s in chosen[:size]:
        c = s.candidate
        niche = None
        if c.niche_id is not None and c.niche_slug is not None and c.niche_label is not None:
            niche = NicheOut(id=c.niche_id, slug=c.niche_slug, label=c.niche_label)
        teaser = TeaserOut(
            title=c.title,
            niche=niche,
            country="KE",
            county_code=c.county_code,
            maturity=c.maturity,
            ask=c.ask,
            problem_statement=c.problem_statement,
            impact_claims=c.impact_claims,
            summary=c.summary,
        )
        items.append(
            PreviewItem(
                proposal_id=c.proposal_id,
                owner_handle=c.owner_handle,
                published_at=c.published_at,
                teaser=teaser,
                score=s.score,
                why=matched_on(s),
                keywords_found=list(s.keywords_found),
            )
        )
    return PreviewOut(
        items=items,
        total=len(chosen),
        window_days=weights.first_run_days,
        digest_size=size,
        note=on_new_note(weights.first_run_days) if body.frequency is ScoutFrequency.ON_NEW else None,
    )


def on_new_note(days: int) -> str:
    """Preview's note for an ``on_new`` scout: it never runs over the window Preview shows. [[COPY-REVIEW]]"""
    return f"Shows what the last {days} days would have matched; this scout sends new proposals only."


@router.get(f"{PREFIX}/{{scout_id}}")
async def get_scout(scout_id: UUID, org: OrgMember, db: Db) -> ScoutOut:
    return await scout_out(db, await _own_scout(db, org.org_id, scout_id))


@router.patch(f"{PREFIX}/{{scout_id}}")
async def update_scout(scout_id: UUID, body: ScoutPatch, org: OrgAdmin, db: Db, settings: SettingsDep) -> ScoutOut:
    """Change the form, or pause or resume the scout (``paused``)."""
    weights = get_weights()
    scout = await _own_scout(db, org.org_id, scout_id)
    changes = body.model_dump(exclude_unset=True)
    paused = changes.pop("paused", None)
    for required in (
        "niches",
        "min_fit",
        "frequency",
        "language",
        "include_keywords",
        "exclude_keywords",
        "counties",
        "maturity",
        "recipients",
    ):
        if required in changes and changes[required] is None:
            raise invalid("invalid_scout", f"{required} cannot be empty.")
    ent = await entitlements.for_subject(db, settings, org_id=org.org_id)
    frequency = changes.get("frequency")
    if frequency is not None and frequency is not scout.frequency:
        check_frequency(settings, ent, frequency)
    if paused is False and scout.paused_at is not None:  # resuming counts against the plan again
        limit = ent.limit(SCOUT_AGENTS)
        used = await _active_scouts(db, org.org_id, but=scout.id)
        if limit is not None and used >= limit:
            raise entitlements.PlanLimitExceeded(settings, ent, SCOUT_AGENTS, limit=limit, used=used)
        check_frequency(settings, ent, frequency or scout.frequency)
    await check_form(
        db,
        org.org_id,
        weights,
        niches=changes.get("niches"),
        counties=changes.get("counties"),
        budget_band=changes.get("budget_band"),
        recipients=changes.get("recipients"),
    )
    for name, value in changes.items():
        setattr(scout, name, value)
    if paused is True and scout.paused_at is None:
        scout.paused_at = (await db.execute(_NOW)).scalar_one()
    elif paused is False:
        scout.paused_at = None
    await audit(
        db,
        "scout.updated",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="scout",
        subject_id=scout.id,
        payload={"fields": sorted(changes), "paused": paused},
    )
    await _commit(db)
    await db.refresh(scout)
    return await scout_out(db, scout)


@router.delete(f"{PREFIX}/{{scout_id}}", status_code=204)
async def delete_scout(scout_id: UUID, org: OrgAdmin, db: Db) -> Response:
    """Delete the scout with its runs and matches."""
    scout = await _own_scout(db, org.org_id, scout_id)
    await db.execute(delete(ScoutAgent).where(ScoutAgent.id == scout.id))
    await audit(
        db,
        "scout.deleted",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="scout",
        subject_id=scout_id,
        payload={},
    )
    await _commit(db)
    return Response(status_code=204)
