"""The evidence clock: a Tier-2 view and the acceptances before it are stamped on the shared clock (REQ-PROV-06).

Closes the residual revision 0013 kept (its security review's eighth note). The prior-knowledge window
(``app_prior_knowledge_window``; docs/spec/06 6.4 pt 5) opens at the organisation's first Tier-2 view,
``min(document_views.started_at)``, which revision 0002's ``evidence_time_guard()`` stamped with the database clock
(``now()``), and closes at the end of the 10th Kenyan business day after it, judged on the shared clock
(``app_nairobi_today()``, from ``app_clock_now()``). Once a dev, test or staging stack had moved its test clock (the
demo walkthrough does), every new window was "closed on ..." the moment it opened, so no declaration could be shown.

``evidence_time_guard()`` is replaced in place (``CREATE OR REPLACE``: same signature, owner, SECURITY INVOKER, pinned
search_path and ACL, EXECUTE revoked from PUBLIC; revision 0002's four BEFORE INSERT triggers keep calling it). It
still sets each evidence time on insert whatever the writer sends, for every role, the owner included, and raises on
any other table as before; only the clock of three of the four times changes:

- ``document_views.started_at`` (a Tier-2 view): ``app_clock_now()``. Its readers: ``app_prior_knowledge_window``
  (its window closes on the shared clock), the render's mark (``viewed_at``) and "Who has seen this", and the ``/me``
  activity calendar (``bridge.me.activity``, whose ranges are on the shared clock).
- ``nda_acceptances.accepted_at`` and ``legal_acceptances.accepted_at`` (the Evaluation NDA and the Master Enterprise
  Terms, the access path's other evidence): ``app_clock_now()``. Their readers only order by them (the earliest
  acceptance: ``bridge.legal.nda``, ``bridge.proposals.access``), test that a row exists (``bridge.proposals.access``,
  the seed) or show the time (the full-proposal page); no reader, function, policy or CHECK compares them with a clock.
  On a moved stack they now fall on the clock of the grant before them (``disclosure_grants.granted_at``, which the API
  writes as ``app_clock_now()``) and of the view after them, instead of days before both.
- ``attestations.created_at`` stays ``now()``: an attestation is made in its registration's transaction, whose
  ``proposal_versions.registered_at`` is ``now()`` (``proposal_versions_guard()``, revision 0002) and whose proofs (the
  certificate, the RFC 3161 and OpenTimestamps tokens) are on real time. Moved alone, it would postdate the
  registration it was made at on a moved stack.

``app_clock_now()`` is the database clock plus the test clock's offset where the owner enabled it (dev, test and
staging databases; ``app_set_test_clock`` refuses elsewhere), so in production the three times stay the database's
real time. One difference holds everywhere, as for every other time on the shared clock: ``app_clock_now()`` reads
``clock_timestamp()``, the moment of the insert, where ``now()`` is the start of its transaction (two views in one
transaction now carry their own instants). The test clock only moves forward, so on a moved stack a new stamp never
precedes an earlier one and the earliest view or acceptance stays the earliest; rows stamped before this revision
keep their times.

The column defaults (``now()``: revision 0002 and the ORM's ``func.now()``) are unchanged: the BEFORE INSERT trigger
replaces whatever a default or a writer gives. bridge_app, the only application role that inserts these rows, already
executes ``app_clock_now()`` and reads ``test_clock`` (revision 0003); definer functions insert as the owner.

Not destructive: one function body changes; no table, column, constraint, policy, trigger or grant does, and no row is
touched. The downgrade restores revision 0002's body byte for byte (rows stamped meanwhile keep their times).

Operating rules for the code that uses this schema (revision 0002's, unchanged): leave the evidence times out and read
them back. Compare a Tier-2 view's or an acceptance's time with the shared clock (``app_clock_now()``,
``app_nairobi_today()``), never with ``now()``; an attestation's belongs with its version's ``registered_at``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0013: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last).
# CREATE OR REPLACE keeps the function's owner and ACL (EXECUTE revoked from PUBLIC by revision 0002) and its triggers.
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- Evidence times are the database's: when an attestation was made, the Master Enterprise Terms or an NDA accepted and
-- a Tier-2 view started is set on insert, whatever the writer sends (the registered_at rule). An attestation's on the
-- database clock, as the registration it is made in; an acceptance's and a view's on the shared clock (revision 0014),
-- as the grant before them and the prior-knowledge window after them.
CREATE OR REPLACE FUNCTION evidence_time_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_TABLE_NAME = 'attestations' THEN
        NEW.created_at := now();
    ELSIF TG_TABLE_NAME IN ('legal_acceptances', 'nda_acceptances') THEN
        NEW.accepted_at := public.app_clock_now();
    ELSIF TG_TABLE_NAME = 'document_views' THEN
        NEW.started_at := public.app_clock_now();
    ELSE
        RAISE EXCEPTION 'evidence_time_guard: no evidence time on %', TG_TABLE_NAME USING ERRCODE = 'internal_error';
    END IF;
    RETURN NEW;
END;
$$;
"""

# Revision 0002's evidence_time_guard(), verbatim (its body must match byte for byte), restored on downgrade.
EVIDENCE_TIME_GUARD_0002 = r"""
CREATE OR REPLACE FUNCTION evidence_time_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_TABLE_NAME = 'attestations' THEN
        NEW.created_at := now();
    ELSIF TG_TABLE_NAME IN ('legal_acceptances', 'nda_acceptances') THEN
        NEW.accepted_at := now();
    ELSIF TG_TABLE_NAME = 'document_views' THEN
        NEW.started_at := now();
    ELSE
        RAISE EXCEPTION 'evidence_time_guard: no evidence time on %', TG_TABLE_NAME USING ERRCODE = 'internal_error';
    END IF;
    RETURN NEW;
END;
$$;
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def upgrade() -> None:
    _run_sql(FUNCTIONS_SQL)


def downgrade() -> None:
    """Revision 0002's body again: the three times go back to the database clock for new rows; rows stamped on the
    shared clock meanwhile keep their times (evidence is never rewritten)."""
    _run_sql(EVIDENCE_TIME_GUARD_0002)
