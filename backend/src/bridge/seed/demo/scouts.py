"""The demo scout (P10; REQ-SCOUT-02, M2 walkthrough step 1). Part of ``python -m bridge.seed --demo``, after the free
plans, so the scout runs on the organisation's plan (``org_claimed``: one weekly scout, a top-3 digest).

Telco A (fixture) gets one weekly scout, created by its owner through ``POST /api/orgs/{org}/scouts``: the
networks and telecommunications niche, the include keywords ``SCOUT_KEYWORDS`` and its reviewer seat as the digest's
recipient. Brian's ``SCOUTED`` proposal is in that niche, carries both keywords, is published through the API and is
pitched to nobody, so Telco A has no engagement for it and the walkthrough's Express interest has somewhere to start;
no other seeded proposal reaches the scout's ``min_fit``. The scout's first scan runs in process, as the worker's
``scouts.scan`` runs one scout (``scan.due`` with no user bound, then ``scan.scan`` bound to the scout's acting member
and organisation, on the shared clock), so the Inbox's Scout matches tab, the match page and the EM3 digest (Mailpit)
show the match as soon as the demo is up. The seed calls no model: the first match carries the rules' "Matched on"
line. Later scans are ``make demo-scouts`` (``python -m bridge.matching run --now`` in the worker, with the configured
LLM) or the worker's own pass after 07:00 EAT; a weekly scout runs once per ISO week (``make demo-clock DAYS=7``).

P9's re-seed rule: the proposal is looked for by its first title (``ensure_proposal``), and the scout step runs only
while Telco A has never had a scout (no ``scout.created`` event on its chain), so a scout people changed, paused or
deleted is left as they left it, and a used demo is never scanned again at start-up. Dev and test only
(``demo_refusal``, checked by the seed before any step).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.config import Settings
from bridge.matching.config import get_weights
from bridge.matching.scan import ScanDeps, clock_now, due, scan
from bridge.models.enums import ProposalAsk, ProposalMaturity, ScoutFrequency
from bridge.notifications.email import EmailProvider
from bridge.seed.demo.data import BRIAN, TELCO_A, DemoProblem, DemoProposal
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one

SCOUT_NICHE: Final = TELCO_A.niche
SCOUT_KEYWORDS: Final = ("fibre", "road works")
SCOUTED = DemoProposal(
    key="P5",
    owner=BRIAN.email,
    title="Road works alerts for buried fibre routes",
    niche=SCOUT_NICHE,
    county="KE-30",
    maturity=ProposalMaturity.PROTOTYPE,
    ask=ProposalAsk.PILOT,
    problem_statement=(
        "Road works and water works cut buried fibre cables without warning, and field teams spend hours finding the"
        " break while customers on the route lose service."
    ),
    impact_claims="A pilot on two busy routes aims to halve the time from a cut to a repair crew on site.",
    summary=(
        "Contractors and county engineers log planned digging on a shared map; the operator's field team is alerted"
        " when road works come near a fibre route, and a cut is located from the nearest open works."
    ),
    approach=(
        "Planned works are entered by contractors on a simple form or imported from the county's permit list. Each is"
        " buffered against the operator's route polylines; works within 50 metres of a route alert the route's field"
        " lead a day before digging starts and again on the day."
    ),
    architecture="One web service with a PostGIS database, a contractor form, a field-team app and an alert worker.",
    pricing="Pilot on two routes for KES 150,000; then KES 2,000 per route kilometre per year.",
    new_problem=DemoProblem(
        title="Fibre cuts from road works",
        statement=(
            "Operators learn that road or water works cut a fibre route only when customers on it lose service."
        ),
    ),
)
_EVER_HAD_A_SCOUT = "SELECT 1 FROM audit_events WHERE org_id = :org AND action = 'scout.created' LIMIT 1"


async def ensure_scout(
    owner: AsyncEngine,
    actors: Actors,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    email: EmailProvider,
    niches: dict[str, UUID],
    report: DemoReport,
) -> None:
    """Telco A's scout and its first scan (see the module docstring); nothing when Telco A ever had a scout."""
    org_id = report.orgs.get(TELCO_A.legal_name)
    if org_id is None or TELCO_A.owner is None:
        raise DemoSeedError(f"{TELCO_A.legal_name} is not there to get a scout")
    if await _one(owner, _EVER_HAD_A_SCOUT, org=org_id) is not None:
        return
    reviewer = report.users[TELCO_A.seats[1].email]
    form = {
        "niches": [str(niches[SCOUT_NICHE])],
        "include_keywords": list(SCOUT_KEYWORDS),
        "frequency": ScoutFrequency.WEEKLY.value,
        "recipients": [str(reviewer)],
    }
    actor = await actors.get(TELCO_A.owner.email)
    created = await actor.call("POST", f"/api/orgs/{org_id}/scouts", json=form, expect=(201,))
    scout_id = UUID(created.json()["id"])
    report.did(f"scout of {TELCO_A.legal_name} ({SCOUT_NICHE}: {', '.join(SCOUT_KEYWORDS)})")
    deps = ScanDeps(factory=factory, settings=settings, email=email, weights=get_weights())
    found = [d for d in await due(factory, await clock_now(factory), ScoutFrequency.WEEKLY) if d.scout_id == scout_id]
    if not found:
        raise DemoSeedError(f"the new scout of {TELCO_A.legal_name} is not due: its first scan did not run")
    outcome = await scan(deps, found[0], ScoutFrequency.WEEKLY)
    if outcome.status != "completed":
        raise DemoSeedError(f"the first scan of {TELCO_A.legal_name}'s scout {outcome.status} ({outcome.reason})")
    recipients = len(outcome.digest.recipients) if outcome.digest is not None else 0
    report.did(f"first scan of {TELCO_A.legal_name}'s scout: {outcome.matched} matched, digest to {recipients}")
