"""Tags may expire, and the expiry job lists what is due (REQ-ENG-10 part, REQ-PROP-03; AC-PROP-3):
``app_close_tag(tag, status)`` and ``app_engagements_due_for_expiry(now)``.

AC-PROP-3 wants ``tags.status = 'expired'`` once the engagement made from the tag expires. Until now nothing could
write it: bridge_app's UPDATE policy on ``tags`` (revision 0002) lets the developer set ``withdrawn`` only, and
``app_close_tag(p_tag)`` closes a tag without changing its status, so the expiry job (task P19-A) left an expired
engagement's tag closed but ``delivered``.

``app_close_tag(p_tag uuid)`` (revision 0002) is replaced by ``app_close_tag(p_tag uuid, p_status tag_status DEFAULT
NULL) RETURNS boolean`` (SECURITY DEFINER, ``search_path = pg_catalog, public, pg_temp``, EXECUTE revoked from PUBLIC
and granted to bridge_app only, as before). It locks the tag (FOR UPDATE) and returns whether this call closed it:

- ``p_status`` NULL: revision 0002's behaviour, unchanged (the developer, or for a delivered tag a member of the
  organisation with owner, admin, signatory or reviewer; the status is kept). Existing callers
  (``SELECT app_close_tag(:tag_id)``) resolve to it through the default.
- ``p_status`` ``withdrawn`` or ``expired``: the tag's developer only (the bound job acts as the developer), and only an
  open tag takes the status: a closed tag keeps the status it closed with (false is returned), so a withdrawn tag is
  never relabelled expired. Any other status is refused (invalid_parameter_value); a member of the organisation, a
  stranger or an unbound session gets insufficient_privilege.
- ``expired`` also needs, checked in SQL (object_not_in_prerequisite_state otherwise): the tag's engagement, the one
  engagement of the tag's proposal and organisation (``uq_engagements_proposal_id_org_id``) of the tag's developer
  with origin ``tagged`` (the engagement made from a delivered tag), is in state ``EXPIRED``; no other tag of that
  proposal and organisation is ``expired`` already (one expiry, one expired tag: a tag created after the engagement
  ended cannot borrow its expiry); and the open tag is ``delivered``. An organisation's own interest (origin
  ``org_agent_match`` or ``org_browse``) never expires a tag: its ``NO_DEV_RESPONSE`` is the developer's silence, and
  an expired tag counts against the organisation's responsiveness (AC-PROP-3).

Why a function rather than a wider UPDATE policy: a policy's WITH CHECK sees only the new row, so it cannot require
the tag to have been open and delivered before the statement (``tags_guard()`` lets a closed tag move between
closing statuses, so a withdrawn tag could be relabelled expired), and the policy would apply to every UPDATE the
developer's session issues on ``tags``, with no lock on the tag. The function is one fixed transition, under the tag's
row lock, reading the old row and the engagement as the owner, with typed arguments; bridge_app's UPDATE grant and
policy on ``tags`` stay exactly revision 0002's, so its direct write surface does not grow.

``app_engagements_due_for_expiry(p_now timestamptz) RETURNS TABLE (developer_id uuid, engagement_id uuid)`` (new;
SECURITY DEFINER, STABLE, pinned search_path, EXECUTE bridge_app only; the side-states security review): the job
``engagements.expire`` walked every user because no application role reads every tenant's engagements; it now asks
for the engagements the clock may act on and binds to their developers only. Like ``app_scouts_due`` (revision 0005)
it runs only with no user bound (a signed-in request is refused, insufficient_privilege), refuses a NULL time, and
returns ids only (no title, party name, state or date). An engagement is listed, ordered by developer, creation and id:

- in ``ORG_INTEREST``, ``SUBMITTED``, ``UNDER_REVIEW`` or ``INTEREST_CONFIRMED`` once its ``stage_deadline_at`` (or,
  with none, its ``stage_entered_at``) is at or before ``p_now``. A superset of what expires: an engagement expires
  ``expire_bd`` business days after it entered the stage, never before its deadline (``due_bd <= expire_bd``, enforced
  by ``bridge.engagements.policy``; pauses move both alike);
- in ``INFO_REQUESTED`` once its ``stage_deadline_at`` is at or before ``p_now`` (a question pauses the clock and the
  application sets no deadline on it, so today none is listed);
- in ``ON_HOLD`` from the start (00:00 Africa/Nairobi) of the day its ``stage_deadline_at`` falls on, its resume date
  (the job resumes a hold from that moment); a hold without a deadline is never listed.

The job decides again, per engagement, in a session bound to the developer and under the engagement's row lock.

Not destructive: no table, column, policy or grant on a table changes and no row is touched. Tags closed before this
revision keep their status (the expiry job exists only on the P19-A branch, so only dev and demo databases can hold an
expired engagement's ``delivered`` tag; the owner may correct one directly, ``tags_guard()`` allows a closed tag to
move to ``expired``). The downgrade restores revision 0002's function byte for byte with its grant; tags already
``expired`` stay valid under revision 0006 (a closing status, closed).

Operating rules for the code that uses this schema:

- When the system expires a tagged engagement (origin ``tagged``), append the ``EXPIRED`` event first, then call
  ``app_close_tag(tag_id, 'expired')`` in the same session bound to the engagement's developer; for any other
  ending, and for an expiry of an organisation's interest, keep calling ``app_close_tag(tag_id)``.
- A refusal (insufficient_privilege, object_not_in_prerequisite_state) means the tag is not this engagement's to
  expire: do not retry it with another status.
- The expiry job calls ``app_engagements_due_for_expiry(now)`` (the shared clock's time, or the run's ``now``) from a
  session with no user bound, then acts on each listed engagement in a session bound to its developer, deciding there
  whether it is due; it never treats the list as the decision.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0006: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS). SECURITY DEFINER functions run as
# bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- Closes an open tag (docs/spec/06 6.3: one open engagement or held tag per developer and organisation) and returns
-- whether this call closed it. Without a status (revision 0002): the developer, or for a delivered tag a member of
-- the organisation who may act on it, closes it and the status is kept (an engagement that ends, e.g. DECLINED).
-- With a status, the tag's developer only (the expiry job is bound to the developer): withdrawn, or expired when the
-- engagement made from the tag (origin tagged; one per proposal and organisation) has expired, no other tag of the
-- pair took that expiry, and the tag is delivered (AC-PROP-3). A closed tag keeps the status it closed with; nothing
-- reopens a tag (tags_guard()); closed_at is not in the app's UPDATE grant.
CREATE FUNCTION app_close_tag(p_tag uuid, p_status tag_status DEFAULT NULL) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_tag public.tags%ROWTYPE;
BEGIN
    IF p_status IS NOT NULL AND p_status NOT IN ('withdrawn', 'expired') THEN
        RAISE EXCEPTION 'app_close_tag: a tag closes as withdrawn or expired, or keeps its status'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT * INTO v_tag FROM public.tags WHERE id = p_tag FOR UPDATE;
    IF NOT FOUND OR public.app_user_id() IS NULL OR NOT coalesce(
        v_tag.developer_id = public.app_user_id()
        OR (v_tag.status = 'delivered'
            AND public.app_is_member(v_tag.org_id, '{owner,admin,signatory,reviewer}')),
        false
    ) THEN
        RAISE EXCEPTION 'app_close_tag: the developer or a member of the tagged organisation only'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_status IS NOT NULL AND v_tag.developer_id <> public.app_user_id() THEN
        RAISE EXCEPTION 'app_close_tag: only the developer withdraws or expires their tag'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_status = 'expired' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.engagements e
             WHERE e.proposal_id = v_tag.proposal_id AND e.org_id = v_tag.org_id
               AND e.developer_id = v_tag.developer_id AND e.origin = 'tagged' AND e.state = 'EXPIRED'
        ) THEN
            RAISE EXCEPTION 'app_close_tag: a tag expires only once the engagement made from it has expired'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.tags t
             WHERE t.proposal_id = v_tag.proposal_id AND t.org_id = v_tag.org_id AND t.id <> v_tag.id
               AND t.status = 'expired'
        ) THEN
            RAISE EXCEPTION 'app_close_tag: the engagement''s expiry already expired another tag'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
    END IF;
    IF v_tag.closed_at IS NOT NULL THEN
        RETURN false;
    END IF;
    IF p_status = 'expired' AND v_tag.status <> 'delivered' THEN
        RAISE EXCEPTION 'app_close_tag: only a delivered tag expires'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.tags
       SET status = coalesce(p_status, status), closed_at = now(), updated_at = now()
     WHERE id = p_tag;
    RETURN true;
END;
$$;

-- The engagements the clock may act on at p_now (job engagements.expire; AC-PROP-3): ids only, so the job binds to
-- their developers instead of walking every user (no application role reads every tenant's engagements). Called with
-- no user bound (a signed-in request learns nothing about other parties' engagements). A superset of what is due,
-- never less: ORG_INTEREST, SUBMITTED, UNDER_REVIEW and INTEREST_CONFIRMED once the stage deadline (without one, the
-- stage's entry) is at or before p_now, since a stage expires expire_bd business days after its entry and never
-- before its deadline (due_bd <= expire_bd); INFO_REQUESTED once its deadline is (none is set while the clock is
-- paused); ON_HOLD from 00:00 Africa/Nairobi on the day of its deadline, the resume date. The job decides again.
CREATE FUNCTION app_engagements_due_for_expiry(p_now timestamptz)
    RETURNS TABLE (developer_id uuid, engagement_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_engagements_due_for_expiry: the engagements.expire job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'app_engagements_due_for_expiry: name the time' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT e.developer_id, e.id
      FROM public.engagements e
     WHERE CASE
           WHEN e.state IN ('ORG_INTEREST', 'SUBMITTED', 'UNDER_REVIEW', 'INTEREST_CONFIRMED')
               THEN coalesce(e.stage_deadline_at, e.stage_entered_at) <= p_now
           WHEN e.state = 'INFO_REQUESTED' THEN e.stage_deadline_at <= p_now
           WHEN e.state = 'ON_HOLD'
               THEN (date_trunc('day', e.stage_deadline_at AT TIME ZONE 'Africa/Nairobi')
                     AT TIME ZONE 'Africa/Nairobi') <= p_now
           ELSE false
           END
     ORDER BY e.developer_id, e.created_at, e.id;
END;
$$;
"""

# EXECUTE grants (every function of this revision has EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    # the engagement code: closing a tag when its engagement ends, expiring it when the system expires the engagement
    "app_close_tag(uuid, tag_status)": ("bridge_app",),
    # the engagements.expire job, with no user bound (ids only)
    "app_engagements_due_for_expiry(timestamptz)": ("bridge_app",),
}

# Revision 0002's app_close_tag, verbatim (its body must match byte for byte), restored on downgrade with its grant.
APP_CLOSE_TAG_0002 = r"""
-- Closes an open tag (docs/spec/06 6.3: one open engagement or held tag per developer and organisation) without
-- changing its status: the developer, or for a delivered tag a member of the organisation who may act on it (the
-- Phase 3 state machine closes tags when their engagement ends, e.g. DECLINED). Returns whether this call closed it.
-- Nothing reopens a tag (tags_guard()); closed_at is not in the app's UPDATE grant.
CREATE FUNCTION app_close_tag(p_tag uuid) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_tag public.tags%ROWTYPE;
BEGIN
    SELECT * INTO v_tag FROM public.tags WHERE id = p_tag FOR UPDATE;
    IF NOT FOUND OR public.app_user_id() IS NULL OR NOT coalesce(
        v_tag.developer_id = public.app_user_id()
        OR (v_tag.status = 'delivered'
            AND public.app_is_member(v_tag.org_id, '{owner,admin,signatory,reviewer}')),
        false
    ) THEN
        RAISE EXCEPTION 'app_close_tag: the developer or a member of the tagged organisation only'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_tag.closed_at IS NOT NULL THEN
        RETURN false;
    END IF;
    UPDATE public.tags SET closed_at = now(), updated_at = now() WHERE id = p_tag;
    RETURN true;
END;
$$;
"""
APP_CLOSE_TAG_0002_SIGNATURE = "app_close_tag(uuid)"


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql(grants: dict[str, tuple[str, ...]]) -> str:
    statements: list[str] = []
    for signature, roles in grants.items():
        statements.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        statements.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(statements)


def upgrade() -> None:
    # A new argument is a new signature: the one-argument function goes (its callers resolve to the new one through
    # the default), in the same transaction.
    _run_sql(f"DROP FUNCTION {APP_CLOSE_TAG_0002_SIGNATURE};")
    _run_sql(FUNCTIONS_SQL)
    _run_sql(_grant_sql(FUNCTION_GRANTS))


def downgrade() -> None:
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in FUNCTION_GRANTS))
    _run_sql(APP_CLOSE_TAG_0002)
    _run_sql(_grant_sql({APP_CLOSE_TAG_0002_SIGNATURE: ("bridge_app",)}))
