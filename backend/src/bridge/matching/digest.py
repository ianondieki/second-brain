"""EM3, the scout digest (REQ-SCOUT-03; docs/spec/06 6.8, 6.10; REQUIREMENTS.md §5 N02; AC-SCOUT-1, AC-MAIL-5).

Rendered by code from a fixed template (``notifications/templates/em3.*.j2``): at most ``limits.digest_items`` (10)
items, or 3 on a plan whose ``scout_digest`` is ``top_3``, each with its niche label (AC-REPO-4/b), its fit, "why
this matches" and whether a model wrote it ("AI-drafted") or the rules did. Text written by a developer or a model
(titles, rationales) is one line, quoted and defanged (``bridge.reminders.render``: no link, email address or phone
number a mail client could follow); the HTML part autoescapes. Every link is a platform URL to a signed-in page, and
opening one changes nothing (the matches API has no side effect on GET).

``send`` runs after a scan committed, with the scout's acting member and organisation bound:

1. the scout's undigested matches (``digest_sent_at`` NULL) whose proposal is still published and clear and whose
   developer is not an active member of the organisation (a match found before the author joined: the matches API
   shows it as unavailable and the interest route answers 404; it stays undigested until it is available again),
   read through ``current_version_id`` (Tier 1 only), chosen and ordered exactly as Preview orders them: the rules'
   deterministic score (``rule_breakdown.deterministic``), then the earlier publication, then the proposal id. The
   model never changes which matches are listed (AC-SCOUT-5: the Preview equals the first digest); the final score is
   shown as a figure only;
2. the recipients re-checked at send time (AC-SCOUT-7, AC-SCOUT-8): each still an active member holding reviewer, an
   active user with a verified email address at the organisation's verified domain, of an E1 or E2 organisation that
   is not suspended; a removed recipient gets nothing;
3. per recipient, in a session bound to them and the organisation: the in-app summary (always on) and the email when
   their EM3 email preference is on (mutable, default on; suppressions are ``send_email``'s), once per run (dedupe
   keys ``em3:<run>:<user>`` and ``em3:inapp:<run>:<user>``);
4. when at least one recipient got it, every match read in step 1 is marked ``digest_sent_at`` (the ones beyond the
   digest's size are summarised as "N more in your inbox"), so no match is listed twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.directory.service import niche_label
from bridge.logging import get_logger
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.notifications.in_app import post_in_app
from bridge.notifications.preferences import channel_enabled
from bridge.reminders.render import HELP_PATH, SETTINGS_PATH, defang, name, platform_url, plural, quote

KIND: Final = "em3"
MAX_ITEMS: Final = 10  # docs/spec/06 6.8: a digest lists at most 10 items
MAX_WHY_CHARS: Final = 300
MATCHES_PATH: Final = "/org/inbox?org={org}&tab=matches"
MATCH_PATH: Final = "/org/inbox/matches/{match}?org={org}"
# [[COPY-REVIEW]] where the "why" came from.
WHY_LABELS: Final = {
    "model": "AI-drafted from the teaser",
    "code": "Matched by the scout's rules",
    "demo_fallback": "Matched by the scout's rules. Demo fallback: no model wrote an explanation",
}
_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Item:
    """One digest line, from the match and the proposal's current teaser (raw values; ``render`` defangs them)."""

    match_id: UUID
    title: str | None
    niche: str | None
    score: int
    why: str
    why_source: str  # model | code | demo_fallback
    maturity: str | None = None
    county: str | None = None


@dataclass(frozen=True, slots=True)
class Digest:
    org_id: UUID
    org_name: str
    items: tuple[Item, ...]
    total: int  # undigested matches, the listed ones included


class EmailParts(NamedTuple):
    subject: str
    text: str
    html: str


def subject(digest: Digest) -> str:
    return f"Scout digest: {plural(digest.total, 'new matching proposal')} for {name(digest.org_name, fallback='you')}"


def render(digest: Digest, *, base_url: str, product: str) -> EmailParts:
    """EM3's two parts from one set of code-filled, defanged values."""
    if not 0 < len(digest.items) <= MAX_ITEMS:
        raise ValueError(f"EM3 lists 1 to {MAX_ITEMS} matches")
    org = str(digest.org_id)
    items = []
    for item in digest.items:
        why = defang(item.why)
        details = " · ".join(value for value in (item.maturity, name(item.county or "", fallback="")) if value)
        items.append(
            {
                "title": quote(item.title, fallback="Untitled proposal"),
                "niche": name(item.niche, fallback="Niche not given"),
                "score": item.score,
                "details": details,
                "why": why if len(why) <= MAX_WHY_CHARS else why[: MAX_WHY_CHARS - 1].rstrip() + "…",
                "why_label": WHY_LABELS.get(item.why_source, WHY_LABELS["code"]),
                "url": platform_url(base_url, MATCH_PATH.format(match=item.match_id, org=org)),
            }
        )
    shown = len(digest.items)
    more = ""
    if digest.total > shown:
        more = f"{plural(digest.total - shown, 'more match', 'more matches')} in your inbox."
    values: dict[str, Any] = {
        "subject": subject(digest),
        "headline": f"Your scout found {plural(digest.total, 'new proposal')} that match its settings."
        + ("" if shown == digest.total else f" The top {shown} are below."),
        "items": items,
        "more": more,
        "matches_url": platform_url(base_url, MATCHES_PATH.format(org=org)),
        "settings_url": platform_url(base_url, SETTINGS_PATH),
        "help_url": platform_url(base_url, HELP_PATH),
        "product": name(product, fallback="Bridge"),
        "org_name": name(digest.org_name, fallback="your organisation"),
    }
    plain_text = _ENV.get_template("em3.txt.j2").render(values)
    return EmailParts(values["subject"], plain_text, _ENV.get_template("em3.html.j2").render(values))


# ------------------------------------------------------------------------------------------------------ sending

_UNDIGESTED = text(
    "SELECT m.id, m.score, m.rationale, m.rationale_demo_fallback, m.rule_breakdown ->> 'why_source' AS why_source,"
    " v.title, v.maturity, r.name AS county_name, v.county_code, n.name_en AS niche_name, pn.name_en AS parent_name"
    " FROM agent_matches m"
    " JOIN proposals p ON p.id = m.proposal_id AND p.status = 'published' AND p.moderation_state = 'clear'"
    " AND NOT EXISTS (SELECT 1 FROM memberships om WHERE om.org_id = m.org_id AND om.user_id = p.owner_id"
    " AND om.status = 'active')"
    " JOIN proposal_versions v ON v.id = p.current_version_id"
    " LEFT JOIN niches n ON n.id = v.niche_id LEFT JOIN niches pn ON pn.id = n.parent_id"
    " LEFT JOIN regions r ON r.code = v.county_code"
    " WHERE m.scout_id = :scout AND m.org_id = :org AND m.digest_sent_at IS NULL"
    " ORDER BY coalesce(CAST(m.rule_breakdown ->> 'deterministic' AS integer), m.score) DESC, p.published_at, p.id"
)
_RECIPIENTS = text(
    "SELECT u.id, CAST(u.email AS text) AS email FROM users u"
    " JOIN memberships ms ON ms.user_id = u.id AND ms.org_id = :org AND ms.status = 'active'"
    " AND ms.roles && CAST('{reviewer}' AS org_role[])"
    " JOIN organizations o ON o.id = ms.org_id"
    " WHERE u.id = ANY(:recipients) AND u.status = 'active' AND u.email_verified_at IS NOT NULL"
    " AND o.verified_domain IS NOT NULL AND o.verification IN ('e1', 'e2') AND o.suspended_at IS NULL"
    " AND lower(split_part(CAST(u.email AS text), '@', 2)) = lower(CAST(o.verified_domain AS text))"
    " ORDER BY u.id"
)
_ORG = text("SELECT legal_name FROM organizations WHERE id = :org")
_MARK = text(
    "UPDATE agent_matches SET digest_sent_at = app_clock_now() WHERE id = ANY(:ids) AND digest_sent_at IS NULL"
)


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: UUID
    email: str


@dataclass(frozen=True, slots=True)
class Sent:
    """What one digest did: the matches it listed and marked, and each recipient's email status (None: in-app
    only, their EM3 email is off)."""

    listed: tuple[UUID, ...]
    marked: tuple[UUID, ...]
    recipients: dict[UUID, DeliveryStatus | None]


def _item(row: Any) -> Item:
    source = "demo_fallback" if row.rationale_demo_fallback else (row.why_source or "code")
    return Item(
        match_id=row.id,
        title=row.title,
        niche=niche_label(row.niche_name, row.parent_name) if row.niche_name else None,
        score=int(row.score),
        why=row.rationale or "",
        why_source=source,
        maturity=row.maturity,
        county=row.county_name or row.county_code,
    )


async def compose(db: AsyncSession, scout_id: UUID, org_id: UUID, size: int) -> tuple[Digest, tuple[UUID, ...]]:
    """The digest of the scout's undigested matches, and the ids to mark once it is sent."""
    rows = (await db.execute(_UNDIGESTED, {"scout": scout_id, "org": org_id})).all()
    org_name = (await db.execute(_ORG, {"org": org_id})).scalar_one_or_none() or "your organisation"
    digest = Digest(org_id, str(org_name), tuple(_item(row) for row in rows[:size]), len(rows))
    return digest, tuple(row.id for row in rows)


async def recipients(db: AsyncSession, org_id: UUID, listed: Sequence[UUID]) -> list[Recipient]:
    """The scout's recipients who may still receive it (re-checked now)."""
    if not listed:
        return []
    rows = (await db.execute(_RECIPIENTS, {"org": org_id, "recipients": list(listed)})).all()
    return [Recipient(row.id, row.email) for row in rows]


async def _deliver(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    parts: EmailParts,
    *,
    run_id: UUID,
    org_id: UUID,
    person: Recipient,
    link: str,
) -> DeliveryStatus | None:
    async with factory() as db:
        await bind_tenant(db, user_id=person.user_id, org_id=org_id)
        await post_in_app(
            db,
            user_id=person.user_id,
            org_id=org_id,
            kind=KIND,
            title=parts.subject[:200],
            body=None,
            link=link,
            dedupe_key=f"em3:inapp:{run_id}:{person.user_id}",
        )
        status = None
        if await channel_enabled(db, person.user_id, KIND, NotificationChannel.EMAIL):
            message = EmailMessage(to=person.email, subject=parts.subject, text=parts.text, html=parts.html, tag=KIND)
            delivery = await send_email(
                db,
                provider,
                message=message,
                kind=KIND,
                user_id=person.user_id,
                org_id=org_id,
                dedupe_key=f"em3:{run_id}:{person.user_id}",
            )
            status = delivery.status
        await db.commit()
    return status


async def send(
    db: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    *,
    scout_id: UUID,
    org_id: UUID,
    run_id: UUID,
    listed_recipients: Sequence[UUID],
    size: int,
) -> Sent:
    """Send the scout's digest (see the module docstring). ``db`` is bound to the scout's acting member and
    organisation; each recipient gets a session of ``factory`` bound to them."""
    digest, ids = await compose(db, scout_id, org_id, size)
    if not digest.items:
        return Sent((), (), {})
    people = await recipients(db, org_id, listed_recipients)
    if not people:
        log.info("scouts.digest_skipped", scout_id=str(scout_id), reason="no_recipient")
        return Sent((), (), {})
    parts = render(digest, base_url=settings.public_base_url, product=settings.product_name)
    link = MATCHES_PATH.format(org=org_id)
    statuses: dict[UUID, DeliveryStatus | None] = {}
    for person in people:
        try:
            statuses[person.user_id] = await _deliver(
                factory, provider, parts, run_id=run_id, org_id=org_id, person=person, link=link
            )
        except Exception as exc:  # one recipient never stops the others; the matches stay for the inbox
            log.error("scouts.digest_failed", scout_id=str(scout_id), error_type=type(exc).__name__)
    if not statuses:
        return Sent((), (), {})
    await db.execute(_MARK, {"ids": list(ids)})
    await db.commit()
    log.info("scouts.digest_sent", scout_id=str(scout_id), items=len(digest.items), recipients=len(statuses))
    return Sent(tuple(i.match_id for i in digest.items), ids, statuses)
