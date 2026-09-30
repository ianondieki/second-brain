"""Demo seed steps for trending and "Recommended for you" (P12; REQ-TREND-01, REQ-TREND-02, REQ-PERS-01, REQ-PERS-03),
so Discover and Home show something on ``make demo``.

- **Liked niches** through the app (``PUT /api/me/niches``, each developer signed in): Amina likes Microfinance,
  Networks & telecommunications and Agriculture; Brian likes County government, Microfinance and Health.
- **Profiling consent** through the app (``PUT /api/me/consents``): Amina turns it on, so her list uses her own
  proposals (f1) and track record (f9); Brian keeps the default (off), so his is ranked on his liked niches, his
  county and public facts only.
- **Signals** have no application path in a four-organisation demo: trends count at least 3 distinct organisations,
  and the demo has two E2 fixtures. So the owner role writes simulated ``scout_match`` and ``org_interest`` signals
  for the demo proposals, as P10's code writes them (a pseudonymous actor digest and organisation digest, no id or
  name), from "simulated organisation" pseudonyms that belong to no account: steady weekly activity over the last
  ten weeks (the niche baselines), then a burst this week for P2 and P1, so their problems and projects trend. The
  README lists Discover's numbers as simulated.

Idempotent and safe on a used demo (P9's rules): liked niches are set only for a developer who has none, and the
consent only for one who never decided it (a choice made in the app is kept). A signal's id is derived from its
Africa/Nairobi date, the proposal, the kind and the organisation, and its time from that date (00:05 plus a few
minutes, never after the run): a second run on the same day inserts nothing, and a run days or weeks later adds only
the dates the earlier runs did not cover (at most one signal per proposal, kind, organisation and date, however
often ``make demo`` starts), which keeps the demo's trends alive without piling up.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.seed.demo.data import AMINA, BRIAN, P1, P2, P3, P4, DemoDeveloper
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _one

NAIROBI: Final = ZoneInfo("Africa/Nairobi")
SIGNAL_NAMESPACE: Final = uuid.UUID("8f0f4a52-6c1e-4d3b-9a57-2f1d4b7e9c10")  # the demo's signal ids only
PSEUDONYM_LABEL: Final = "bridge-demo-trend-v1"
LIKED: Final = {
    AMINA.email: ("microfinance-saccos", "networks-telecommunications", "agriculture"),
    BRIAN.email: ("county-government", "microfinance-saccos", "health"),
}
PROFILING_ON: Final = frozenset({AMINA.email})


@dataclass(frozen=True, slots=True)
class DemoSignals:
    proposal: str  # proposal key
    kind: str  # scout_match or org_interest
    orgs: int  # simulated organisations (at least 3, or nothing counts)
    weeks: tuple[int, ...]  # weeks ago with one signal per organisation (the baseline)
    burst: tuple[int, ...] = ()  # days ago with one signal per organisation (this week's rise)


SIGNALS: Final = (
    DemoSignals(P2.key, "scout_match", orgs=4, weeks=tuple(range(2, 11)), burst=(0, 1, 2)),
    DemoSignals(P2.key, "org_interest", orgs=3, weeks=(3, 6, 9), burst=(0, 1)),
    DemoSignals(P1.key, "scout_match", orgs=3, weeks=tuple(range(2, 11)), burst=(0, 2)),
    DemoSignals(P3.key, "scout_match", orgs=3, weeks=tuple(range(1, 11))),  # steady: a baseline, not a trend
    DemoSignals(P4.key, "org_interest", orgs=3, weeks=(), burst=(1,)),
)
_INSERT = text(
    "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash, ts) VALUES (:id, :item, :kind, :actor, :org,"
    " :ts) ON CONFLICT (id) DO NOTHING"
)


def pseudonym(*parts: object) -> bytes:
    """A 32-byte digest standing for a simulated organisation or person (no account has it)."""
    return hashlib.sha256("|".join((PSEUDONYM_LABEL, *map(str, parts))).encode()).digest()


def signal_rows(report: DemoReport, now: datetime) -> list[dict[str, object]]:
    """The demo's signals as of ``now``: each keyed and timed by its Africa/Nairobi date, so a run on any later day
    finds the dates it shares with an earlier run already there."""
    today = now.astimezone(NAIROBI).date()
    rows = []
    for plan in SIGNALS:
        item = report.proposals.get(plan.proposal)
        if item is None:
            continue
        days = [7 * w for w in plan.weeks] + list(plan.burst)
        for day in days:
            for n in range(plan.orgs):
                org = pseudonym("org", n)
                actor = org if plan.kind == "scout_match" else pseudonym("person", n)  # a scout acts as its org
                target = today - timedelta(days=day)
                key = f"{target.isoformat()}:{plan.proposal}:{plan.kind}:{n}"
                at = datetime.combine(target, time(0, 5), tzinfo=NAIROBI) + timedelta(minutes=7 * n)
                rows.append(
                    {
                        "id": uuid.uuid5(SIGNAL_NAMESPACE, key),
                        "item": item,
                        "kind": plan.kind,
                        "actor": actor,
                        "org": org,
                        "ts": min(at, now - timedelta(minutes=1 + n)),  # today's never in the future
                    }
                )
    return rows


async def ensure_liked_niches(
    owner: AsyncEngine, actors: Actors, dev: DemoDeveloper, niches: dict[str, UUID], report: DemoReport
) -> None:
    user = report.users.get(dev.email)
    if user is None:
        return
    found = await _one(owner, "SELECT 1 FROM developer_niches WHERE user_id = :u AND kind = 'liked' LIMIT 1", u=user)
    if found is not None:
        return
    missing = [slug for slug in LIKED[dev.email] if slug not in niches]
    if missing:
        raise DemoSeedError(f"niches {missing} are missing: run the reference seed first")
    actor = await actors.get(dev.email)
    await actor.call("PUT", "/api/me/niches", json={"liked": [str(niches[s]) for s in LIKED[dev.email]]})
    report.did(f"liked niches of {dev.email}")


async def ensure_profiling(owner: AsyncEngine, actors: Actors, dev: DemoDeveloper, report: DemoReport) -> None:
    user = report.users.get(dev.email)
    if user is None or dev.email not in PROFILING_ON:
        return
    decided = await _one(owner, "SELECT 1 FROM consents WHERE user_id = :u AND purpose = 'profiling' LIMIT 1", u=user)
    if decided is not None:
        return
    actor = await actors.get(dev.email)
    version = (await actor.call("GET", "/api/consents")).json()["version"]
    await actor.call("PUT", "/api/me/consents", json={"profiling": {"granted": True, "version": version}})
    report.did(f"profiling consent of {dev.email}")


async def seed_signals(owner: AsyncEngine, report: DemoReport) -> None:
    async with owner.begin() as conn:
        now: datetime = (await conn.execute(text("SELECT app_clock_now()"))).scalar_one()
        rows = signal_rows(report, now)
        inserted = 0
        for row in rows:
            inserted += int(getattr(await conn.execute(_INSERT, row), "rowcount", 0) or 0)
    if inserted:
        report.did(f"simulated trend signals ({inserted})")


async def seed_trending(owner: AsyncEngine, actors: Actors, niches: dict[str, UUID], report: DemoReport) -> None:
    """The P12 steps, in order: liked niches, the profiling consent, the simulated signals."""
    for dev in (AMINA, BRIAN):
        await ensure_liked_niches(owner, actors, dev, niches, report)
        await ensure_profiling(owner, actors, dev, report)
    await seed_signals(owner, report)
