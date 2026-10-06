"""Schema v8 (P22 track B): This week's events, event reminders and technology trend cards.

REQ-DEV-02 (D-60, D-61). Design: ``docs/platform/tasks/P22.md`` section "B — This week" and its "Defaults taken"
paragraph. Additive: four new tables (``events``, ``event_reminders``, ``trend_cards``, ``trend_card_sources``) with
their policies, triggers and grants, and ten new functions (three of them trigger functions, one internal). No enum
type (text columns with CHECKs); no new tenancy class (events are PUBLISHED, reminders USER, the trend tables
CURATED). Nothing of revisions 0001 to 0009 is changed or dropped; the triggers reuse ``block_mutation()`` (revision
0002), the clock ``app_clock_now()`` (revision 0003), ``app_text_set_is_valid`` (revision 0005) and
``app_is_developer()`` and ``app_nairobi_today()`` (revision 0009). The upgrade is additive; the downgrade is
destructive (it drops the events, reminders and trend cards: see ``downgrade()``).

Changelog: amended in place on 2026-10-06 (REQ-DEV-02, D-60) to add ``app_trend_job_state(since)``, the weekly trend
job's only reader of the cards. Revision 0010 is merged on the P22 feature branch only and was deployed nowhere but
reset demo stacks, so the function joins it instead of a revision 0011. A database migrated with the earlier 0010 (a
demo stack) is recreated: ``alembic upgrade head`` sees 0010 as applied and never re-applies an edited revision.

Who reads and writes what (bridge_app; there is no worker role: a job is bridge_app with no user bound, as revisions
0007 to 0009's jobs; a "developer" is ``app_is_developer()``: an active user with a developer profile and no staff
role, so staff decide and never read as developers):

- ``events`` (PUBLISHED: an organisation's when ``org_id`` is set, the platform's otherwise; bridge_app: SELECT of
  every column but ``decided_by``, INSERT of ``id``, ``org_id``, ``created_by`` and the content columns, UPDATE of the
  content columns only; no DELETE). Readers: staff admin and moderator every event; a developer the
  published ones; an active member of the organisation (narrowed by ``app.org_id``) its events in any status; nobody
  else any (organisation-only accounts read no other organisation's events, and no session without a user reads
  any). Writers: an editor of the organisation (owner, admin, signatory or reviewer, the Briefs' editors; narrowed by
  ``app.org_id``) posts a draft for it as themselves, or a staff admin posts a draft with no organisation
  ("Platform"); the poster edits the content columns of their own draft only. The organisation's E2 verification is
  the application's check, as for Briefs (``_require_e2``): the policy does not read ``organizations.verification``.
  ``status`` moves only from ``draft`` to ``published`` or ``rejected`` (``app_decide_event``) or ``cancelled``, and
  from ``published`` to ``cancelled`` (``app_cancel_event``), with ``decided_by``/``decided_at`` and
  ``cancelled_at``; ``events_guard`` (BEFORE INSERT OR UPDATE, every role, the owner too) refuses a county that is
  not one (a ``regions`` row of kind ``country``, such as ``KE``; an unknown code is the foreign key's), any other
  status change, any
  change of ``org_id``, ``created_by`` or ``created_at``, a decision column changed without the status, anything
  else changed with the status, and a content change of an event that is not a draft; and it owns ``updated_at``:
  the shared clock on every content or status change, whatever was sent, and unchanged otherwise (so a reviewer's
  ``p_seen`` names exactly the content they read).
  CHECKs: a title of 1 to 120 characters and a description of 1 to 1,000 (no control character; the description may
  hold tabs and line breaks); it ends after it starts and at most 3 days later; online with a join URL and neither
  venue nor county, or in person at a venue (1 to 160) in a county (``regions.code`` of kind ``county``: the
  guard) without a join URL; ``join_url``
  and ``link``, when set, https on an ASCII host (letters, digits, dots and hyphens, an optional port; no user info, no
  whitespace or control character; ``app_research_source_is_valid``'s rule) of at most 400 characters; a draft has no
  decision, a published or rejected event has one (who and when), only a cancelled event has ``cancelled_at``.
- ``event_reminders`` (USER; bridge_app: SELECT, INSERT of ``user_id`` and ``event_id``, DELETE; no UPDATE). A
  developer's "Remind me", one row per developer and event: their own rows only, inserted on a published event that
  has not ended (``ends_at > app_clock_now()``) and deleted by Decline. Nobody else reads a reminder (no staff policy,
  so no developer's reminders are ever read by another developer, an organisation or staff). The reminder job lists
  due rows only through ``app_event_reminders_due(now)``.
- ``trend_cards`` and ``trend_card_sources`` (CURATED; bridge_app: SELECT only, of every card column but
  ``decided_by``). Staff admin reads every card and source, a developer the published cards and their sources, nobody
  else any (staff moderators, organisation-only accounts and unbound sessions included); the weekly job (no user bound)
  learns only whether a card that is not rejected is recent and which excerpts such cards cite, through
  ``app_trend_job_state(since)``. Written only by ``app_create_trend_candidate`` (a ``candidate`` with 1 to 5 sources at
  positions 1 to 5) and decided only by ``app_decide_trend_card``. ``trend_cards_guard`` (every role): a card's content,
  trace id, named organisations and creation time never change; its status moves once, ``candidate`` to ``published``
  (only with a source) or ``rejected``. ``trend_card_sources_guard`` (every role): a source is added only to a candidate
  card (read FOR SHARE: a decision in flight is waited for); ``trend_card_sources_no_update`` (``block_mutation()``):
  never changed.
  CHECKs: title 1 to 120, summary 1 to 600, a topic slug of lower-case words joined by hyphens (at most 40), a
  confidence of 0 to 1 (three decimals), a trace id ``^[A-Za-z0-9._:-]{1,80}$``, named organisations as
  ``problems.named_orgs`` (at most 10 distinct names of 1 to 200 characters, no control character), a decision
  complete with its status (``published_at`` only and always on a published card); a source's https URL (as above), a
  publisher (1 to 160), the published and retrieved dates (retrieved on or after published), a quote (1 to 600), an
  ``excerpt_ref`` (``^[A-Za-z0-9_.:-]{1,32}$``, revision 0005's) and what it supports (1 to 400), none with a control
  character.

Indexes: ``ix_events_status_starts_at`` (the week's published events, soonest first; the due reminders),
``ix_events_org_id_created_at`` (an organisation's events), the partial ``ix_events_county_code_published`` (the Home
strip's county); ``pk_event_reminders`` (user_id, event_id) serves a developer's reminders and
``ix_event_reminders_event_id`` an event's; ``ix_trend_cards_status_published_at`` (the published cards, the daily
rotation); ``uq_trend_card_sources_card_id_position`` serves a card's sources.

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``; each refuses with a message naming itself):

- ``app_decide_event(event, decision, seen)``: staff admin or moderator (insufficient_privilege); ``publish`` or
  ``reject`` and the ``updated_at`` the reviewer read (invalid_parameter_value when NULL); an unknown event
  no_data_found. Locks the event FOR UPDATE, then refuses (object_not_in_prerequisite_state) an event that is not a
  draft, one whose ``updated_at`` is not ``seen`` ("the event changed since it was reviewed", the app's 409
  ``changed_since_review``: the poster edited it after the reviewer read it; for both decisions) and ``publish`` of
  an event that has ended (``ends_at <= app_clock_now()``; "the event is over", the app's 409 ``event_over``; it
  may still be rejected). Sets the status, ``decided_by`` (the caller) and ``decided_at`` (the shared clock).
- ``app_cancel_event(event)``: staff admin or moderator, or an editor of the event's organisation (narrowed by
  ``app.org_id``); the staff admin who posted a platform event is staff. One refusal (insufficient_privilege, "no
  event the caller may cancel with that id") for an unknown event and for any other caller, so it tells nobody that a
  draft exists. A draft or published event only (object_not_in_prerequisite_state otherwise); sets ``cancelled`` and
  ``cancelled_at``.
- ``app_event_reminders_due(now)`` -> (user_id, event_id): the reminder job only, with no user bound
  (insufficient_privilege otherwise; invalid_parameter_value for a NULL time), as ``app_saved_searches_due``
  (revision 0008). The reminders of active users on published events that have not ended at ``now`` and start on
  ``now``'s Nairobi day or the next (N27 the morning of, N26 the day before): ids only, a superset the job decides on
  again, bound to each developer.
- ``app_create_trend_candidate(card, sources)`` -> the card's id: the trend job (bridge_app with no user bound) or a
  staff admin (the manual run; insufficient_privilege otherwise). ``card`` is an object of ``title``, ``summary``,
  ``topic_slug`` (strings) and optionally ``confidence`` (a number of 0 to 1, rounded to three decimals, or null),
  ``llm_trace_id`` (a string or null) and ``named_orgs`` (an array of strings); ``sources`` an array of 1 to 5 objects
  of exactly ``url``, ``publisher``, ``published_date`` and ``retrieved_at`` (YYYY-MM-DD, real dates, retrieved on or
  after published and not after the Nairobi day of the shared clock), ``quote``, ``excerpt_ref`` and ``support``, all
  strings, by ``trend_source_is_valid(source)`` (INVOKER, no EXECUTE grant). Any malformed card or source is
  invalid_parameter_value; nothing is written then. Inserts the candidate (title, summary, publisher and support
  trimmed; the quote verbatim) and its sources at positions 1 to 5 in the order given, in one call.
- ``app_decide_trend_card(card, decision)``: staff admin only (insufficient_privilege); ``publish`` or ``reject``
  (invalid_parameter_value); an unknown card no_data_found; a decided card object_not_in_prerequisite_state. Locks the
  card FOR UPDATE; ``publish`` sets ``published``, ``published_at`` and the decision, ``reject`` sets ``rejected`` and
  the decision.
- ``app_trend_job_state(since)`` -> one row (recent, cited_refs): the weekly trend job only, with no user bound
  (insufficient_privilege otherwise; invalid_parameter_value for a NULL time), as ``app_event_reminders_due``.
  ``recent``: a card that is not rejected (a candidate or a published one) was created at or after ``since`` (the
  job's 6-day rule); ``cited_refs``: the distinct ``excerpt_ref`` of the sources of every card that is not rejected,
  sorted (an empty array when there is none; the job leaves those excerpts out). Nothing else of any card: no id,
  title, status or time.

Operating rules for the code that uses this schema:

- Post an event as the caller, for an organisation only after the E2 check (403 ``verification_required`` as Briefs),
  leaving ``status``, the decision columns and the times out (read them back). Map the INSERT policy's refusal to 403
  for a member without an editor role, 404 for a non-member; an UPDATE of a published event matches no row (the
  policy), so check the status first and answer 409. Never select ``events.decided_by`` or ``trend_cards.decided_by``
  (deferred with raiseload): who decided is in the audit event the app writes in the decision's transaction.
- Decisions and cancellations only through ``app_decide_event``, ``app_cancel_event`` and ``app_decide_trend_card``
  (the app writes the audit event in the same transaction; insufficient_privilege from ``app_cancel_event`` is 404).
  The staff review screen carries the event's ``updated_at`` as read and sends it back as ``p_seen``; map "changed
  since it was reviewed" to 409 ``changed_since_review`` (reload and review again) and "the event is over" to 409
  ``event_over``.
  Serve the ``.ics`` and the Google link for published events only (read under the caller's RLS).
- Remind me: INSERT (user_id, event_id) as the developer (the policy's refusal of a draft, cancelled or past event is
  409 or 404; a repeat is the primary key's unique violation, or ``ON CONFLICT DO NOTHING``); Decline is a DELETE.
  The job: ``app_event_reminders_due(now)`` with no user bound, then per developer a session bound to them
  (``bind_tenant``) that reads the reminder and the event again (a cancelled event is gone from a developer's view),
  the consent and preferences as EM7 does, and writes ``notification_deliveries`` and ``in_app_notifications`` under
  that binding, keyed once per kind, developer and event.
- Trend cards: the weekly job (no user bound) first reads ``app_trend_job_state(now - 6 days)`` (``recent``: nothing
  is drafted; ``cited_refs``: the excerpts left out of the call; the manual run reads the cards as the staff admin
  instead), then calls ``app_create_trend_candidate`` with no user bound (the manual run as the staff admin), never
  with a model-written URL or excerpt id that the code did not take from the publisher list; the database checks the
  shape, not the allowlist or the research checks.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("events", "event_reminders", "trend_cards", "trend_card_sources")
RLS_TABLES = NEW_TABLES

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Column-scoped where the
# database owns a column (status, decisions, times) or the app must never read one (who decided).
EVENT_CONTENT = "title, description, starts_at, ends_at, online, venue, county_code, join_url, link"
EVENT_READABLE = f"id, org_id, created_by, {EVENT_CONTENT}, status, decided_at, cancelled_at, created_at, updated_at"
CARD_READABLE = (
    "id, title, summary, topic_slug, status, confidence, llm_trace_id, decided_at, published_at, named_orgs, created_at"
)
APP_GRANTS: dict[str, str] = {
    "events": (
        f"SELECT ({EVENT_READABLE}), INSERT (id, org_id, created_by, {EVENT_CONTENT}), UPDATE ({EVENT_CONTENT})"
    ),
    "event_reminders": "SELECT, INSERT (user_id, event_id), DELETE",
    "trend_cards": f"SELECT ({CARD_READABLE})",
    "trend_card_sources": "SELECT",
}

# CHECK expressions, verbatim from the ORM models (bridge.events.models, bridge.trends.models).
EVENT_STATUSES = ("draft", "published", "rejected", "cancelled")
CARD_STATUSES = ("candidate", "published", "rejected")
EXCERPT_REF = "^[A-Za-z0-9_.:-]{1,32}$"
TOPIC_SLUG = "^[a-z0-9]+(-[a-z0-9]+)*$"
TRACE_ID = "^[A-Za-z0-9._:-]{1,80}$"


def _text(column: str, max_chars: int) -> str:
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _https_url(column: str, max_chars: int = 400) -> str:
    return (
        f"{column} ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]]*)?$' AND {column} !~ '[[:cntrl:]]'"
        f" AND char_length({column}) <= {max_chars}"
    )


DESCRIPTION_VALID = (
    "description ~ '[^[:space:]]' AND char_length(description) <= 1000"
    " AND description !~ '[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]'"
)
PLACE_VALID = (
    "(online AND join_url IS NOT NULL AND venue IS NULL AND county_code IS NULL)"
    " OR (NOT online AND venue IS NOT NULL AND county_code IS NOT NULL AND join_url IS NULL)"
)
SPAN_VALID = "ends_at > starts_at AND ends_at <= starts_at + interval '3 days'"
EVENT_DECISION_COMPLETE = (
    "(decided_by IS NULL) = (decided_at IS NULL) AND (status = 'cancelled') = (cancelled_at IS NOT NULL)"
    " AND CASE status WHEN 'draft' THEN decided_at IS NULL WHEN 'cancelled' THEN true ELSE decided_at IS NOT NULL END"
)
CARD_DECISION_COMPLETE = (
    "(decided_by IS NULL) = (decided_at IS NULL) AND (status = 'candidate') = (decided_at IS NULL)"
    " AND (status = 'published') = (published_at IS NOT NULL)"
)


class Policy(NamedTuple):
    """One RLS policy for one command, named ``<role>_<command>[_<suffix>]`` (unique per table)."""

    table: str
    command: str
    using: str | None = None
    check: str | None = None
    role: str = "bridge_app"
    suffix: str = ""

    @property
    def name(self) -> str:
        return f"{self.role}_{self.command.lower()}" + (f"_{self.suffix}" if self.suffix else "")

    def create_sql(self) -> str:
        # USING filters existing rows (SELECT, UPDATE, DELETE); WITH CHECK validates new rows (INSERT, UPDATE).
        shape = {"SELECT": (True, False), "INSERT": (False, True), "UPDATE": (True, True), "DELETE": (True, False)}
        if shape.get(self.command) != (self.using is not None, self.check is not None):
            raise ValueError(f"malformed policy: {self}")
        sql = f"CREATE POLICY {self.name} ON {self.table} AS PERMISSIVE FOR {self.command} TO {self.role}"
        if self.using is not None:
            sql += f" USING ({self.using})"
        if self.check is not None:
            sql += f" WITH CHECK ({self.check})"
        return sql + ";"


_STAFF = "app_is_staff('{admin,moderator}')"
_STAFF_ADMIN = "app_is_staff('{admin}')"
_ORG_MEMBER = "app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id())"  # revisions 0002, 0006, 0008
# The poster of an event: an editor of its organisation (the Briefs' editors, revision 0002's _ORG_EDITOR) posting for
# it as themselves, or a staff admin posting for the platform (no organisation). E2 is the application's check.
_POSTER = (
    "((org_id IS NOT NULL AND created_by = app_user_id() AND app_is_member(org_id, '{owner,admin,signatory,reviewer}')"
    " AND (app_org_id() IS NULL OR org_id = app_org_id()))"
    f" OR (org_id IS NULL AND created_by = app_user_id() AND {_STAFF_ADMIN}))"
)
_OWN = "user_id = app_user_id()"

POLICIES: tuple[Policy, ...] = (
    # --- events (PUBLISHED): staff every event, developers the published ones, members their organisation's ---
    Policy(
        "events",
        "SELECT",
        f"{_STAFF} OR (status = 'published' AND app_is_developer()) OR (org_id IS NOT NULL AND {_ORG_MEMBER})",
    ),
    Policy("events", "INSERT", check=f"{_POSTER} AND status = 'draft'"),
    Policy("events", "UPDATE", f"{_POSTER} AND status = 'draft'", f"{_POSTER} AND status = 'draft'"),
    # --- event_reminders (USER): the developer's own, on a published event that has not ended ---
    Policy("event_reminders", "SELECT", _OWN),
    Policy(
        "event_reminders",
        "INSERT",
        check=f"{_OWN} AND app_is_developer() AND EXISTS (SELECT 1 FROM events e"
        " WHERE e.id = event_reminders.event_id AND e.status = 'published' AND e.ends_at > app_clock_now())",
    ),
    Policy("event_reminders", "DELETE", _OWN),
    # --- trend_cards, trend_card_sources (CURATED): staff admin every row, developers the published cards' ---
    Policy("trend_cards", "SELECT", f"{_STAFF_ADMIN} OR (status = 'published' AND app_is_developer())"),
    Policy(
        "trend_card_sources",
        "SELECT",
        f"{_STAFF_ADMIN} OR (app_is_developer() AND EXISTS (SELECT 1 FROM trend_cards c"
        " WHERE c.id = trend_card_sources.card_id AND c.status = 'published'))",
    ),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0009: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; internal and trigger functions to nobody).
# SECURITY DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED). Each locks the one row it
# decides FOR UPDATE; a trend source's insert reads its card FOR SHARE.
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- A staff admin or moderator publishes or rejects a draft event once (D-60: nothing unmoderated is shown), as
-- themselves, at the shared clock, on exactly the content they reviewed: p_seen is the updated_at they read (the
-- database's, events_guard), and a draft edited since is refused under the row lock; an event that has ended is
-- never published (it may be rejected). The app writes the audit event in the same transaction.
CREATE FUNCTION app_decide_event(p_event uuid, p_decision text, p_seen timestamptz) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
    v_ends timestamptz;
    v_updated timestamptz;
    v_now timestamptz := public.app_clock_now();
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_decide_event: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('publish', 'reject') THEN
        RAISE EXCEPTION 'app_decide_event: the decision is publish or reject' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_seen IS NULL THEN
        RAISE EXCEPTION 'app_decide_event: name the updated_at the reviewer read'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT e.status, e.ends_at, e.updated_at INTO v_status, v_ends, v_updated
      FROM public.events e WHERE e.id = p_event FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_decide_event: no event with that id' USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status <> 'draft' THEN
        RAISE EXCEPTION 'app_decide_event: only a draft event is decided (this one is %)', v_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF v_updated IS DISTINCT FROM p_seen THEN  -- the app's 409 changed_since_review, for both decisions
        RAISE EXCEPTION 'app_decide_event: the event changed since it was reviewed'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF p_decision = 'publish' AND v_ends <= v_now THEN  -- the app's 409 event_over; a reject is still allowed
        RAISE EXCEPTION 'app_decide_event: the event is over, so it is never published'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.events
       SET status = CASE p_decision WHEN 'publish' THEN 'published' ELSE 'rejected' END,
           decided_by = public.app_user_id(), decided_at = v_now
     WHERE id = p_event;
END;
$$;

-- A draft or published event is cancelled by staff (admin or moderator; the staff admin who posted a platform event
-- is one) or by an editor of its organisation (owner, admin, signatory or reviewer, narrowed by app.org_id). An
-- unknown event and any other caller get the same refusal, so nobody learns that a draft exists. The organisation and
-- poster never change (events_guard), so the caller is checked before the row is locked.
CREATE FUNCTION app_cancel_event(p_event uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_org uuid;
    v_status text;
    v_now timestamptz := public.app_clock_now();
BEGIN
    SELECT e.org_id INTO v_org FROM public.events e WHERE e.id = p_event;
    IF NOT FOUND OR NOT (
        public.app_is_staff('{admin,moderator}')
        OR (v_org IS NOT NULL AND public.app_is_member(v_org, '{owner,admin,signatory,reviewer}')
            AND (public.app_org_id() IS NULL OR v_org = public.app_org_id()))
    ) THEN
        RAISE EXCEPTION 'app_cancel_event: no event the caller may cancel with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT e.status INTO v_status FROM public.events e WHERE e.id = p_event FOR UPDATE;
    IF NOT FOUND THEN  -- deleted meanwhile (the owner)
        RAISE EXCEPTION 'app_cancel_event: no event the caller may cancel with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_status NOT IN ('draft', 'published') THEN
        RAISE EXCEPTION 'app_cancel_event: only a draft or published event is cancelled (this one is %)', v_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.events SET status = 'cancelled', cancelled_at = v_now WHERE id = p_event;
END;
$$;

-- The reminders the event reminder job may act on at p_now (N26 the day before at 18:00, N27 the morning of at 08:00,
-- Nairobi): ids only, so the job binds to each developer instead of reading every developer's reminders (no
-- application role reads them), as app_saved_searches_due (revision 0008). Called with no user bound (a signed-in
-- request learns nothing about other developers' reminders). Active users, published events that have not ended at
-- p_now and start on p_now's Nairobi day or the next. A superset of what is due: the job decides again, bound to the
-- developer.
CREATE FUNCTION app_event_reminders_due(p_now timestamptz)
    RETURNS TABLE (user_id uuid, event_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_today date;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_event_reminders_due: the event reminder job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'app_event_reminders_due: name the time' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    v_today := (p_now AT TIME ZONE 'Africa/Nairobi')::date;
    RETURN QUERY
    SELECT r.user_id, r.event_id
      FROM public.event_reminders r
      JOIN public.events e ON e.id = r.event_id
      JOIN public.users u ON u.id = r.user_id
     WHERE e.status = 'published' AND e.ends_at > p_now AND u.status = 'active'
       AND e.starts_at >= (v_today::timestamp AT TIME ZONE 'Africa/Nairobi')
       AND e.starts_at < ((v_today + 2)::timestamp AT TIME ZONE 'Africa/Nairobi')
     ORDER BY r.user_id, r.event_id;
END;
$$;

-- One source of a trend card: an object of exactly url, publisher, published_date, retrieved_at, quote, excerpt_ref and
-- support, all strings; the URL https on an ASCII host (letters, digits, dots and hyphens, an optional port; no user
-- info, no whitespace; app_research_source_is_valid's rule) of at most 400 characters; a publisher (1 to 160), a quote
-- (1 to 600) and what it supports (1 to 400), none blank or with a control character; the excerpt's id; the published
-- and retrieved dates as YYYY-MM-DD, real dates (any malformed one is the same false), retrieved on or after published
-- and not after the Nairobi day of the shared clock. Internal: only app_create_trend_candidate() calls it, as the
-- owner. VOLATILE: it reads the clock.
CREATE FUNCTION trend_source_is_valid(p_source jsonb) RETURNS boolean
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_published date;
    v_retrieved date;
BEGIN
    IF p_source IS NULL OR jsonb_typeof(p_source) <> 'object' THEN
        RETURN false;
    END IF;
    IF (SELECT count(*) FROM jsonb_each(p_source) AS kv(key, value)
         WHERE kv.key IN ('url', 'publisher', 'published_date', 'retrieved_at', 'quote', 'excerpt_ref', 'support')
           AND jsonb_typeof(kv.value) = 'string') <> 7
       OR (SELECT count(*) FROM jsonb_object_keys(p_source)) <> 7 THEN
        RETURN false;
    END IF;
    IF NOT (p_source->>'url' ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]]*)?$'
            AND p_source->>'url' !~ '[[:cntrl:]]' AND char_length(p_source->>'url') <= 400)
       OR NOT (p_source->>'publisher' ~ '[^[:space:]]' AND char_length(p_source->>'publisher') <= 160
               AND p_source->>'publisher' !~ '[[:cntrl:]]')
       OR NOT (p_source->>'quote' ~ '[^[:space:]]' AND char_length(p_source->>'quote') <= 600
               AND p_source->>'quote' !~ '[[:cntrl:]]')
       OR NOT (p_source->>'support' ~ '[^[:space:]]' AND char_length(p_source->>'support') <= 400
               AND p_source->>'support' !~ '[[:cntrl:]]')
       OR p_source->>'excerpt_ref' !~ '^[A-Za-z0-9_.:-]{1,32}$'
       OR p_source->>'published_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
       OR p_source->>'retrieved_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        RETURN false;
    END IF;
    BEGIN
        v_published := CAST(p_source->>'published_date' AS date);
        v_retrieved := CAST(p_source->>'retrieved_at' AS date);
    EXCEPTION WHEN data_exception THEN
        RETURN false;
    END;
    RETURN v_published <= v_retrieved AND v_retrieved <= public.app_nairobi_today();
END;
$$;

-- The only way a trend card enters the database (REQ-DEV-02; D-60): the weekly trend job (bridge_app with no user
-- bound) or a staff admin's manual run. A candidate (never shown to developers until a staff admin publishes it) with
-- a title of 1 to 120 characters, a summary of 1 to 600 (both trimmed, neither with a control character), a topic slug
-- of lower-case words joined by hyphens (at most 40), an optional confidence (0 to 1, rounded to three decimals), an
-- optional trace id of the generating call and optional named organisations (at most 10 distinct names of 1 to 200
-- characters without a control character), and 1 to 5 valid sources (trend_source_is_valid), written at positions 1
-- to 5 in the order given. Card and sources are written in one call: a refused source leaves nothing behind. The
-- publisher allowlist and the research checks are the application's. Returns the card's id.
CREATE FUNCTION app_create_trend_candidate(p_card jsonb, p_sources jsonb) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_card uuid := public.uuid7();
    v_title text;
    v_summary text;
    v_slug text;
    v_trace text;
    v_confidence numeric;
    v_orgs text[] := '{}';
    v_valid boolean;
BEGIN
    IF NOT (public.app_user_id() IS NULL OR public.app_is_staff('{admin}')) THEN
        RAISE EXCEPTION 'app_create_trend_candidate: the trend job with no user bound, or staff admin'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_card IS NULL OR jsonb_typeof(p_card) <> 'object' THEN
        v_valid := false;
    ELSE
        v_valid := NOT EXISTS (
            SELECT 1 FROM jsonb_each(p_card) AS kv(key, value)
             WHERE kv.key NOT IN ('title', 'summary', 'topic_slug', 'confidence', 'llm_trace_id', 'named_orgs')
                OR (kv.key IN ('title', 'summary', 'topic_slug') AND jsonb_typeof(kv.value) <> 'string')
                OR (kv.key = 'confidence' AND jsonb_typeof(kv.value) NOT IN ('number', 'null'))
                OR (kv.key = 'llm_trace_id' AND jsonb_typeof(kv.value) NOT IN ('string', 'null'))
                OR (kv.key = 'named_orgs' AND jsonb_typeof(kv.value) <> 'array'));
    END IF;
    IF NOT v_valid THEN
        RAISE EXCEPTION 'app_create_trend_candidate: the card is an object of title, summary and topic_slug, and'
            ' optionally confidence, llm_trace_id and named_orgs' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    v_title := btrim(p_card->>'title');
    v_summary := btrim(p_card->>'summary');
    v_slug := p_card->>'topic_slug';
    v_trace := p_card->>'llm_trace_id';
    IF v_title IS NULL OR v_title !~ '[^[:space:]]' OR char_length(v_title) > 120 OR v_title ~ '[[:cntrl:]]'
       OR v_summary IS NULL OR v_summary !~ '[^[:space:]]' OR char_length(v_summary) > 600
       OR v_summary ~ '[[:cntrl:]]'
       OR v_slug IS NULL OR v_slug !~ '^[a-z0-9]+(-[a-z0-9]+)*$' OR char_length(v_slug) > 40
       OR (v_trace IS NOT NULL AND v_trace !~ '^[A-Za-z0-9._:-]{1,80}$') THEN
        RAISE EXCEPTION 'app_create_trend_candidate: a title of 1 to 120 characters, a summary of 1 to 600 (neither'
            ' with a control character), a topic slug of lower-case words joined by hyphens (at most 40) and a trace id'
            ' of at most 80 characters, or none' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF jsonb_typeof(p_card->'confidence') = 'number' THEN
        v_confidence := CAST(p_card->>'confidence' AS numeric);
        IF v_confidence < 0 OR v_confidence > 1 THEN
            RAISE EXCEPTION 'app_create_trend_candidate: confidence is 0 to 1, or none'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        v_confidence := round(v_confidence, 3);
    END IF;
    IF p_card ? 'named_orgs' THEN
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_card->'named_orgs') AS n(item)
                    WHERE jsonb_typeof(n.item) <> 'string') THEN
            v_valid := false;
        ELSE
            v_orgs := ARRAY(SELECT n.item FROM jsonb_array_elements_text(p_card->'named_orgs') WITH ORDINALITY
                                               AS n(item, i) ORDER BY n.i);
            v_valid := public.app_text_set_is_valid(v_orgs, 10, 200)
                       AND NOT EXISTS (SELECT 1 FROM unnest(v_orgs) AS o(name) WHERE o.name ~ '[[:cntrl:]]');
        END IF;
        IF NOT v_valid THEN
            RAISE EXCEPTION 'app_create_trend_candidate: named organisations are at most 10 distinct names of 1 to'
                ' 200 characters without a control character' USING ERRCODE = 'invalid_parameter_value';
        END IF;
    END IF;
    IF p_sources IS NULL OR jsonb_typeof(p_sources) <> 'array' THEN
        v_valid := false;
    ELSE
        v_valid := jsonb_array_length(p_sources) BETWEEN 1 AND 5 AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_sources) AS t(source)
             WHERE NOT public.trend_source_is_valid(t.source));
    END IF;
    IF NOT v_valid THEN
        RAISE EXCEPTION 'app_create_trend_candidate: 1 to 5 sources, each with an https URL, a publisher, the'
            ' published and retrieved dates, a quote, an excerpt ref and what it supports'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    INSERT INTO public.trend_cards (id, title, summary, topic_slug, confidence, llm_trace_id, named_orgs)
    VALUES (v_card, v_title, v_summary, v_slug, v_confidence, v_trace, v_orgs);
    INSERT INTO public.trend_card_sources (id, card_id, position, url, publisher, published_date, retrieved_at, quote,
                                           excerpt_ref, support)
    SELECT public.uuid7(), v_card, t.n, t.source->>'url', btrim(t.source->>'publisher'),
           CAST(t.source->>'published_date' AS date), CAST(t.source->>'retrieved_at' AS date), t.source->>'quote',
           t.source->>'excerpt_ref', btrim(t.source->>'support')
      FROM jsonb_array_elements(p_sources) WITH ORDINALITY AS t(source, n)
     ORDER BY t.n;
    RETURN v_card;
END;
$$;

-- A staff admin publishes or rejects a candidate trend card once (D-60: staff-approved), as themselves, at the shared
-- clock; a published card carries its publication time (the label's "human-reviewed on {date}"). The app writes the
-- audit event in the same transaction.
CREATE FUNCTION app_decide_trend_card(p_card uuid, p_decision text) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
    v_now timestamptz := public.app_clock_now();
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_decide_trend_card: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('publish', 'reject') THEN
        RAISE EXCEPTION 'app_decide_trend_card: the decision is publish or reject'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT c.status INTO v_status FROM public.trend_cards c WHERE c.id = p_card FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_decide_trend_card: no trend card with that id' USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status <> 'candidate' THEN
        RAISE EXCEPTION 'app_decide_trend_card: the card was already decided (%)', v_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.trend_cards
       SET status = CASE p_decision WHEN 'publish' THEN 'published' ELSE 'rejected' END,
           decided_by = public.app_user_id(), decided_at = v_now,
           published_at = CASE p_decision WHEN 'publish' THEN v_now END
     WHERE id = p_card;
END;
$$;

-- The weekly trend job's state (REQ-DEV-02, D-60): a session with no user bound reads no trend card (the tables'
-- SELECT policies), so the job asks here, as the reminder job asks app_event_reminders_due. One row: whether a
-- card that is not rejected (a candidate or a published one) was created at or after p_since (the job's 6-day rule:
-- then nothing is drafted), and the distinct excerpt ids the sources of every card that is not rejected cite, sorted
-- (left out of the call; an empty array when there is none). Nothing else of any card: no id, title, status or time.
-- A signed-in session (the manual run's staff admin reads the cards under RLS) is refused, and so is a NULL time.
CREATE FUNCTION app_trend_job_state(p_since timestamptz)
    RETURNS TABLE (recent boolean, cited_refs text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_trend_job_state: the weekly trend job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_since IS NULL THEN
        RAISE EXCEPTION 'app_trend_job_state: name the time' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT EXISTS (SELECT 1 FROM public.trend_cards c WHERE c.status <> 'rejected' AND c.created_at >= p_since),
           ARRAY(SELECT DISTINCT s.excerpt_ref
                   FROM public.trend_card_sources s
                   JOIN public.trend_cards c ON c.id = s.card_id
                  WHERE c.status <> 'rejected'
                  ORDER BY s.excerpt_ref);
END;
$$;

-- An event's organisation, poster and creation time never change; its status moves only from draft to published,
-- rejected or cancelled, or from published to cancelled, and a status change changes nothing else (a cancellation
-- keeps the decision); the decision and cancellation columns change only with the status; only a draft's content
-- changes. updated_at is the database's: the shared clock on every content or status change, whatever was sent, and
-- unchanged otherwise. On INSERT and UPDATE, an event's county is a county: a regions row of kind county, never the
-- country (an unknown code is left to the foreign key). For every role (bridge_app's UPDATE is the poster's draft
-- content by grant and policy). SECURITY INVOKER (regions is readable by every role that writes events).
CREATE FUNCTION events_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_content_changed boolean;
BEGIN
    IF NEW.county_code IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.county_code IS DISTINCT FROM OLD.county_code)
       AND EXISTS (SELECT 1 FROM public.regions r WHERE r.code = NEW.county_code AND r.kind <> 'county') THEN
        RAISE EXCEPTION 'events: an event''s county is one of the counties, not a country'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    v_content_changed := (NEW.title, NEW.description, NEW.starts_at, NEW.ends_at, NEW.online, NEW.venue,
                          NEW.county_code, NEW.join_url, NEW.link)
                         IS DISTINCT FROM (OLD.title, OLD.description, OLD.starts_at, OLD.ends_at, OLD.online,
                                           OLD.venue, OLD.county_code, OLD.join_url, OLD.link);
    IF (NEW.id, NEW.org_id, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.org_id, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'events: an event''s organisation, poster and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT ((OLD.status = 'draft' AND NEW.status IN ('published', 'rejected', 'cancelled'))
                OR (OLD.status = 'published' AND NEW.status = 'cancelled')) THEN
            RAISE EXCEPTION 'events: an event moves only from draft to published, rejected or cancelled, or from'
                ' published to cancelled' USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        IF v_content_changed OR (NEW.status = 'cancelled'
                                 AND (NEW.decided_by, NEW.decided_at) IS DISTINCT FROM (OLD.decided_by, OLD.decided_at))
        THEN
            RAISE EXCEPTION 'events: a decision or a cancellation changes nothing else of the event'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.updated_at := public.app_clock_now();
        RETURN NEW;
    END IF;
    IF (NEW.decided_by, NEW.decided_at, NEW.cancelled_at)
       IS DISTINCT FROM (OLD.decided_by, OLD.decided_at, OLD.cancelled_at) THEN
        RAISE EXCEPTION 'events: the decision and the cancellation change only with the status'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'draft' AND v_content_changed THEN
        RAISE EXCEPTION 'events: only a draft event is edited' USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    NEW.updated_at := CASE WHEN v_content_changed THEN public.app_clock_now() ELSE OLD.updated_at END;
    RETURN NEW;
END;
$$;

-- A trend card's content, trace id, named organisations and creation time never change; it changes once, by its
-- decision, from candidate to published (only with a source) or rejected. For every role (bridge_app holds no UPDATE:
-- app_decide_trend_card). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION trend_cards_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.title, NEW.summary, NEW.topic_slug, NEW.confidence, NEW.llm_trace_id, NEW.named_orgs,
        NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.title, OLD.summary, OLD.topic_slug, OLD.confidence, OLD.llm_trace_id,
                         OLD.named_orgs, OLD.created_at) THEN
        RAISE EXCEPTION 'trend_cards: a card''s content, generating call and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'candidate' OR NEW.status = 'candidate' THEN
        RAISE EXCEPTION 'trend_cards: a card changes only by its one decision, from candidate to published or rejected'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.status = 'published' AND NOT EXISTS (SELECT 1 FROM public.trend_card_sources s WHERE s.card_id = NEW.id)
    THEN
        RAISE EXCEPTION 'trend_cards: a card is published only with a source' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- A source joins only a candidate card (read FOR SHARE: a decision in flight is waited for and its outcome read). For
-- every role (bridge_app holds no INSERT: app_create_trend_candidate). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION trend_card_sources_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
BEGIN
    SELECT c.status INTO v_status FROM public.trend_cards c WHERE c.id = NEW.card_id FOR SHARE;
    IF v_status IS DISTINCT FROM 'candidate' THEN
        RAISE EXCEPTION 'trend_card_sources: sources are added only to a candidate card'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a policy runs its functions with the caller's privileges.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_decide_event(uuid, text, timestamp with time zone)": ("bridge_app",),  # staff admin or moderator
    "app_cancel_event(uuid)": ("bridge_app",),  # staff, or an editor of the event's organisation
    "app_event_reminders_due(timestamp with time zone)": ("bridge_app",),  # the reminder job, no user bound
    "app_create_trend_candidate(jsonb, jsonb)": ("bridge_app",),  # the trend job (no user bound) or staff admin
    "app_decide_trend_card(uuid, text)": ("bridge_app",),  # staff admin
    "app_trend_job_state(timestamp with time zone)": ("bridge_app",),  # the weekly trend job, no user bound
}
INTERNAL_FUNCTIONS = ("trend_source_is_valid(jsonb)",)
TRIGGER_FUNCTIONS = ("events_guard()", "trend_cards_guard()", "trend_card_sources_guard()")

TRIGGERS_SQL = r"""
CREATE TRIGGER events_guard
    BEFORE INSERT OR UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION events_guard();
CREATE TRIGGER trend_cards_guard
    BEFORE UPDATE ON trend_cards
    FOR EACH ROW EXECUTE FUNCTION trend_cards_guard();
CREATE TRIGGER trend_card_sources_guard
    BEFORE INSERT ON trend_card_sources
    FOR EACH ROW EXECUTE FUNCTION trend_card_sources_guard();
CREATE TRIGGER trend_card_sources_no_update
    BEFORE UPDATE ON trend_card_sources
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _create_tables()
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops the events (with the organisations' drafts and the staff decisions), the developers' Remind
    me rows and the trend cards with their sources. Under the CLAUDE.md stop rule a downgrade of a database holding any
    of them is a destructive migration: back the database up and get the human's decision first. The downgrade refuses
    while any of the tables has rows unless it is run with ``-x allow_events_loss=true`` (``alembic -x
    allow_events_loss=true downgrade 0009``). The audit events of decisions and cancellations stay in
    ``audit_events``; queued or sent N26/N27 deliveries stay in ``notification_deliveries``."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_events_loss") == "true"
    holding = [
        table
        for table in NEW_TABLES
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0010 downgrade: {', '.join(holding)} hold the events, the developers' reminders and the trend"
            " cards; back the database up, get the human's decision (CLAUDE.md: destructive migration), then run with"
            " -x allow_events_loss=true"
        )
    # Dropping a table drops its policies, triggers, indexes and grants (block_mutation() is revision 0002's and stays);
    # the policies go with their tables before the functions they call.
    for table in ("event_reminders", "events", "trend_card_sources", "trend_cards"):
        op.drop_table(table)
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )


def _create_tables() -> None:
    op.create_table(
        "events",
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("join_url", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_text("title", 120), name=op.f("ck_events_title_valid")),
        sa.CheckConstraint(DESCRIPTION_VALID, name=op.f("ck_events_description_valid")),
        sa.CheckConstraint(SPAN_VALID, name=op.f("ck_events_span_valid")),
        sa.CheckConstraint(PLACE_VALID, name=op.f("ck_events_place_valid")),
        sa.CheckConstraint(f"venue IS NULL OR ({_text('venue', 160)})", name=op.f("ck_events_venue_valid")),
        sa.CheckConstraint(f"join_url IS NULL OR ({_https_url('join_url')})", name=op.f("ck_events_join_url_valid")),
        sa.CheckConstraint(f"link IS NULL OR ({_https_url('link')})", name=op.f("ck_events_link_valid")),
        sa.CheckConstraint(_in("status", EVENT_STATUSES), name=op.f("ck_events_status_known")),
        sa.CheckConstraint(EVENT_DECISION_COMPLETE, name=op.f("ck_events_decision_complete")),
        sa.ForeignKeyConstraint(["county_code"], ["regions.code"], name=op.f("fk_events_county_code_regions")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_events_created_by_users")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_events_decided_by_users")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_events_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_status_starts_at", "events", ["status", "starts_at"], unique=False)
    op.create_index("ix_events_org_id_created_at", "events", ["org_id", "created_at"], unique=False)
    op.create_index(
        "ix_events_county_code_published",
        "events",
        ["county_code"],
        unique=False,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "event_reminders",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_event_reminders_event_id_events"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_event_reminders_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "event_id", name=op.f("pk_event_reminders")),
    )
    op.create_index("ix_event_reminders_event_id", "event_reminders", ["event_id"], unique=False)
    op.create_table(
        "trend_cards",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topic_slug", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'candidate'"), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("llm_trace_id", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("named_orgs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_text("title", 120), name=op.f("ck_trend_cards_title_valid")),
        sa.CheckConstraint(_text("summary", 600), name=op.f("ck_trend_cards_summary_valid")),
        sa.CheckConstraint(
            f"topic_slug ~ '{TOPIC_SLUG}' AND char_length(topic_slug) <= 40",
            name=op.f("ck_trend_cards_topic_slug_valid"),
        ),
        sa.CheckConstraint(_in("status", CARD_STATUSES), name=op.f("ck_trend_cards_status_known")),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name=op.f("ck_trend_cards_confidence_range")
        ),
        sa.CheckConstraint(
            f"llm_trace_id IS NULL OR llm_trace_id ~ '{TRACE_ID}'", name=op.f("ck_trend_cards_llm_trace_id_valid")
        ),
        sa.CheckConstraint(
            "app_text_set_is_valid(named_orgs, 10, 200) AND array_to_string(named_orgs, ' ') !~ '[[:cntrl:]]'",
            name=op.f("ck_trend_cards_named_orgs_valid"),
        ),
        sa.CheckConstraint(CARD_DECISION_COMPLETE, name=op.f("ck_trend_cards_decision_complete")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_trend_cards_decided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trend_cards")),
    )
    op.create_index("ix_trend_cards_status_published_at", "trend_cards", ["status", "published_at"], unique=False)
    op.create_table(
        "trend_card_sources",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("retrieved_at", sa.Date(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("excerpt_ref", sa.Text(), nullable=False),
        sa.Column("support", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 5", name=op.f("ck_trend_card_sources_position_range")),
        sa.CheckConstraint(_https_url("url"), name=op.f("ck_trend_card_sources_url_valid")),
        sa.CheckConstraint(_text("publisher", 160), name=op.f("ck_trend_card_sources_publisher_valid")),
        sa.CheckConstraint(
            "retrieved_at >= published_date", name=op.f("ck_trend_card_sources_retrieved_after_published")
        ),
        sa.CheckConstraint(_text("quote", 600), name=op.f("ck_trend_card_sources_quote_valid")),
        sa.CheckConstraint(f"excerpt_ref ~ '{EXCERPT_REF}'", name=op.f("ck_trend_card_sources_excerpt_ref_format")),
        sa.CheckConstraint(_text("support", 400), name=op.f("ck_trend_card_sources_support_valid")),
        sa.ForeignKeyConstraint(
            ["card_id"], ["trend_cards.id"], name=op.f("fk_trend_card_sources_card_id_trend_cards"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trend_card_sources")),
        sa.UniqueConstraint("card_id", "position", name=op.f("uq_trend_card_sources_card_id_position")),
    )
