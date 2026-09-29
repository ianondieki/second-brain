"""The platform-wide LLM request count (REQ-LLM-01, D-37): ``app_llm_calls_since(model, since)``.

A free provider slot (P7, ``feat/REQ-LLM-01-providers``) has one daily request quota shared by every tenant, so its cap
must count every tenant's requests, and bridge_app reads only the bound tenant's ``llm_calls`` rows (RLS).
``app_llm_calls_since(p_model varchar, p_since timestamptz) RETURNS bigint`` (SECURITY DEFINER, EXECUTE bridge_app
only) returns the number of ``llm_calls`` rows of ``p_model`` with ``created_at >= p_since`` that reached a provider:
every row except a call refused before sending (any ``blocked_*`` status: the kill switch, the budget and request
caps, the Tier-2 guard, a missing consent) and a Message Batches reservation (``batch_reserved``; the item's
settlement, with its final status, counts once it is written). An unknown status counts (a cap then refuses early,
never late). It returns the count only, never a row, as ``app_llm_spend_usd`` returns the platform's spend only; a
NULL model or start is refused (it would count nothing and open the cap).

Additive: one function, EXECUTE revoked from PUBLIC and granted to bridge_app; nothing of revisions 0001 to 0003 is
changed. The downgrade drops the function.

Operating rule: ``SqlLedger.calls_since`` calls ``app_llm_calls_since(model, since)`` instead of counting the rows the
bound tenant may read; ``InMemoryLedger`` keeps the same exclusions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0003: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS). SECURITY DEFINER functions run as
# bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The platform-wide number of llm_calls rows of p_model since p_since (created_at >= p_since) that reached a
-- provider, for the free providers' daily request caps (D-37): one slot's quota serves every tenant. Left out: calls
-- refused before sending (every blocked_* status) and Message Batches reservations (batch_reserved; the settlement
-- counts). Any other status counts, so a status added later is counted until it is excluded here (fail closed).
-- SECURITY DEFINER: counts every tenant's rows and the platform jobs' whatever the caller may read, and returns the
-- number only.
CREATE FUNCTION app_llm_calls_since(p_model varchar, p_since timestamptz) RETURNS bigint
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF p_model IS NULL OR p_since IS NULL THEN
        RAISE EXCEPTION 'app_llm_calls_since: name the model and the start of the window'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN (SELECT pg_catalog.count(*)
              FROM public.llm_calls c
             WHERE c.model = p_model
               AND c.created_at >= p_since
               AND c.status <> 'batch_reserved'
               AND NOT pg_catalog.starts_with(c.status, 'blocked_'));
END;
$$;
"""

# EXECUTE grants (every function of this revision has EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    # SqlLedger.calls_since: a free slot's daily request cap (P7)
    "app_llm_calls_since(varchar, timestamptz)": ("bridge_app",),
}


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants: list[str] = []
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _run_sql(FUNCTIONS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in FUNCTION_GRANTS))
