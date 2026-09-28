"""Schema v2: repository, directory, provenance and the Tier-2 role set (T2.1).

REQ-REPO-01 (tiered proposal storage, ``proposal_confidential`` behind the Tier-2 roles), REQ-PROV-01 (registration
records, anchors, transparency roots), REQ-TEN-01 (RLS on every new tenant table, the PUBLISHED and STAFF tenancy
classes). Design: ``docs/platform/tasks/REQ-REPO-01.md`` ("T2.1 schema v2 design"). Additive only: 32 new tables,
new enum types, new columns on ``organizations`` and ``users``, one new SELECT policy each on ``organizations`` and
``org_niches``, and one new column grant (``organizations.county_code``). Nothing of revision 0001 is altered or
dropped.

Before upgrading an existing cluster, re-run ``infra/postgres/roles.sql`` (as a superuser) and
``infra/postgres/prepare_db.sql`` (in the database): the five Tier-2 roles and their schema USAGE live there, because
``bridge_owner`` may not create roles. The upgrade checks both and stops with that instruction otherwise.

Tier 2 and the role set (docs/spec/06 6.1):

- ``bridge_app`` has no privilege at all on ``proposal_confidential`` or ``proposal_confidential_embeddings``. It is a
  member of ``tier2_reader``, ``provenance_worker``, ``tier2_embed_worker``, ``tier2_moderation`` and
  ``dsr_exporter`` WITH INHERIT FALSE, SET TRUE (``roles.sql``), so it can only ``SET LOCAL ROLE`` to one of them
  (``bridge.db.as_role``) after the application check; RLS applies to each role with its own policies.
- ``tier2_reader`` reads the owner's rows, or rows ``app_tier2_granted(proposal_id, version_id)`` allows: an active
  Tier >= 2 grant to an E2, unsuspended organisation the current user belongs to with role reviewer, signatory or
  admin and TOTP enrolled, a registered version of a published, clear proposal, the organisation's Master
  Enterprise Terms and this person's Evaluation NDA for this proposal on record, and no WITHDRAWN, DECLINED or
  TERMINATED engagement. It writes only the owner's rows, and only while the version is a draft (trigger).
- ``provenance_worker``, ``tier2_embed_worker`` and ``dsr_exporter`` read the rows of the user the job is bound to
  (``app.user_id``: one tenant per job); ``tier2_moderation`` reads only in a staff context (``app_is_staff``).

Tenancy classes added to ``bridge.models.base.Tenancy`` (the generated RLS tests cover both):

- PUBLISHED (``proposals``, ``proposal_versions``, ``proposal_problems``, ``problems``, ``problem_sources``): the owner
  reads and writes; every signed-in user reads published rows clear of moderation holds; staff admin|moderator read
  everything. ``candidate`` problems are readable by staff only.
- STAFF (``moderation_cases``, ``directory_invitations``, ``proposal_confidential_embeddings``): ``app_is_staff()``
  reads and updates; the app (or the embed worker) inserts.

Privileged changes run only through the SECURITY DEFINER functions below, which check their caller in SQL: moderation
decisions and holds, claim approval (E1 automatic, E1/E2 by staff admin), delisting, D1 confirmation (the OTP hash is
compared in SQL), D2 decisions (staff admin), the KYC image purge bookkeeping, the invitation opt-out and the global
LLM spend, reissuing a claim's email code, closing a tag, and the audit chain heads for the hourly anchor (EXECUTE for
``provenance_worker`` only). ``bridge_app`` holds no UPDATE on ``verification``, ``verification_level``,
``moderation_state``, ``tags.closed_at`` or the claim OTP columns.

Consistency rules by trigger and index: ``proposals.current_version_id`` is a registered version of the proposal and
``draft_version_id`` a draft one. A tag is open while ``closed_at`` IS NULL (one open tag per developer and
organisation, the database form of "one open engagement or held tag"); withdrawn, expired and released tags are
closed, ``app_close_tag`` closes one otherwise (Phase 3: when its engagement ends), and nothing reopens a tag. A
claim's ``otp_attempts`` is cumulative and never reset: its budget is 5 attempts per code issued, with at most 5
reissues (``app_reissue_claim_otp``), after which the claim goes to manual review; one open claim per claimant and
organisation, and one new claim per claimant and organisation per 24 hours.

Evidence is immutable by trigger (AC-IP-2): a registered ``proposal_versions`` row refuses UPDATE and DELETE except
filling its still-empty ``content_hash``, ``prev_version_hash`` and ``manifest_version``; its ``proposal_confidential``
row refuses changes except filling the empty manifest pair; ``provenance_records`` refuses DELETE and any UPDATE other
than filling empty signature/TSA/evidence columns and moving ``status`` forward; ``attestations``, ``nda_acceptances``,
``legal_acceptances``, ``chain_anchors`` and ``transparency_roots`` are append-only. Registering a version needs at
least one linked problem (trigger) and the complete Tier-1 snapshot (CHECK).

Refinements of the task card, all within its rules: ``proposals`` also denormalises the current ``problem_statement``,
``impact_claims`` and ``summary`` (the generated ``search_tsv`` can only read its own row); ``proposal_confidential``
gains ``manifest_nonce`` (the manifest is encrypted under the proposal key and must not reuse the content nonce);
``app_tier2_granted`` takes the version as well as the proposal (drafts are never granted); ``organizations`` gains
``suspended_at`` (the "not suspended" condition of can_view_tier2); ``org_claims`` gains ``otp_verified_at`` (set only
by ``app_confirm_claim_otp``); ``moderation_cases`` gains ``reporter_id``; ``brief_invitations`` carries the brief's
``org_id`` so the two brief policies never read each other recursively. Templates and acceptances are tied by
``(template id, sha256)`` foreign keys, so an accepted template version cannot change; ``nda_templates`` follows its
legal body ON UPDATE CASCADE until an acceptance pins it. The listed-organisations rule is a second SELECT policy
(``bridge_app_select_listed``) next to 0001's, which stays untouched.

Operating rules for the code that uses this schema:

- Switch roles only with ``bridge.db.as_role`` and never commit inside it; write audit events after it returns.
- Tables some callers may insert into but not read back (``moderation_cases``, ``directory_invitations``,
  ``llm_calls`` system rows, ``signal_events``, ``legal_acceptances`` by a claimant, the Tier-2 worker tables) need
  inserts without RETURNING; their ORM models set ``eager_defaults=False``.
- The OTP functions count an attempt even when they return false: commit after calling them.
- Jobs bind the user they act for (``bind_tenant``): the Tier-2 worker roles read only that user's rows.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types created by this revision, frozen here (the ORM enums in bridge.models.enums must match; a test compares).
ENUMS: dict[str, tuple[str, ...]] = {
    "legal_template_kind": ("master_enterprise_terms", "evaluation_nda", "mutual_nda", "tos", "aup"),
    "nda_kind": ("evaluation", "mutual"),
    "problem_source": ("research_agent", "org_brief", "developer"),
    "problem_status": ("candidate", "pending_review", "published", "rejected", "archived"),
    "moderation_state": ("clear", "held", "rejected"),
    "brief_visibility": ("public", "invited"),
    "brief_status": ("draft", "published", "closed"),
    "proposal_status": ("draft", "published", "hidden", "archived"),
    "proposal_maturity": ("idea", "prototype", "mvp", "live"),
    "proposal_ask": ("sale", "licence", "co_build", "pilot", "hire"),
    "tier2_policy": ("auto_tagged", "manual", "niche_e2"),
    "version_status": ("draft", "registered"),
    "av_status": ("pending_upload", "pending_scan", "clean", "infected", "failed"),
    "originality_band": ("none", "some_overlap", "high_overlap"),
    "provenance_status": ("hashed", "signed", "timestamped"),
    "tag_status": (
        "held_unclaimed",
        "held_pending_verification",
        "delivered",
        "withdrawn",
        "expired",
        "released",
    ),
    "engagement_origin": ("tagged", "org_agent_match", "org_browse"),
    "engagement_state": (
        "ORG_INTEREST",
        "SUBMITTED",
        "UNDER_REVIEW",
        "INTEREST_CONFIRMED",
        "PROCUREMENT_ROUTE",
        "CONTACT_MADE",
        "NDA_PENDING",
        "NDA_SIGNED",
        "NEGOTIATION",
        "AGREEMENT_SIGNING",
        "IN_IMPLEMENTATION",
        "DELIVERED",
        "SIGN_OFF",
        "PAYMENT_FINAL",
        "CLOSED",
        "DECLINED",
        "WITHDRAWN",
        "EXPIRED",
        "ON_HOLD",
        "DISPUTED",
        "TERMINATED",
        "INFO_REQUESTED",
    ),
    "engagement_end_reason": (
        "NOT_PRIORITY",
        "ALREADY_IN_PROGRESS_INTERNALLY",
        "BUDGET",
        "NOT_RELEVANT",
        "NEEDS_MATURITY",
        "OTHER",
        "BY_DEVELOPER",
        "NO_REVIEW",
        "NO_DECISION",
        "CONTACT_NOT_MADE",
        "NO_DEV_RESPONSE",
    ),
    "grant_status": ("requested", "active", "revoked", "denied"),
    "grant_source": ("auto_tagged", "manual", "niche_e2", "org_interest"),
    "render_kind": ("html", "pdf", "attachment"),
    "view_duration": ("under_1m", "under_5m", "under_15m", "over_15m"),
    "moderation_source": ("prescreen", "regex", "report", "claim_dispute", "tier2_similarity"),
    "moderation_case_status": ("open", "held", "approved", "rejected", "escalated"),
    "claim_level": ("e1", "e2"),
    "claim_status": ("otp_sent", "dns_pending", "pending_review", "approved", "rejected", "disputed", "withdrawn"),
    "directory_invitation_status": ("proposed", "approved", "sent", "refused"),
    "kyc_status": ("submitted", "approved", "rejected"),
}

# The docs/spec/06 6.1 role set (roles.sql). bridge_app is a member of each WITH INHERIT FALSE, SET TRUE.
TIER2_ROLES = ("tier2_reader", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "dsr_exporter")

# Tables of this revision with Row-Level Security (tenancy org, user, org_or_user, published or staff in the ORM).
RLS_TABLES = (
    "problems",
    "problem_sources",
    "problem_briefs",
    "brief_invitations",
    "proposals",
    "proposal_versions",
    "proposal_problems",
    "proposal_confidential",
    "proposal_confidential_embeddings",
    "proposal_attachments",
    "originality_checks",
    "attestations",
    "tags",
    "engagements",
    "disclosure_grants",
    "nda_acceptances",
    "legal_acceptances",
    "document_views",
    "moderation_cases",
    "org_claims",
    "directory_invitations",
    "phone_verifications",
    "kyc_reviews",
    "llm_calls",
    "provenance_records",
)

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted (proposal_confidential,
# proposal_confidential_embeddings and chain_anchors: none at all). UPDATE is column-scoped where some columns are never
# the app's to change: moderation_state and every key, owner and decision column.
APP_GRANTS: dict[str, str] = {
    "legal_templates": "SELECT",
    "nda_templates": "SELECT",
    "provenance_keys": "SELECT",  # keys are registered by an owner-run command
    "problems": (
        "SELECT, INSERT, UPDATE (title, statement, affected_group, niche_id, country, county_code, embedding,"
        " embed_model, embed_version, updated_at)"
    ),
    "problem_sources": "SELECT, INSERT, DELETE",
    "problem_briefs": "SELECT, INSERT, UPDATE (visibility, budget_band, deadline, status, updated_at)",
    "brief_invitations": "SELECT, INSERT, DELETE",
    "proposals": (
        "SELECT, INSERT, DELETE, UPDATE (status, current_version_id, draft_version_id, title, niche_id, country,"
        " county_code, maturity, ask, problem_statement, impact_claims, summary, teaser_embedding, embed_model,"
        " embed_version, tier2_policy, raw_download_enabled, published_at, hidden_at, updated_at)"
    ),
    # registered_at is the database's (set at registration); the registration hashes are provenance_worker's.
    "proposal_versions": (
        "SELECT, INSERT, DELETE, UPDATE (status, title, niche_id, country, county_code, maturity, ask,"
        " problem_statement, impact_claims, summary, owner_handle, cert_id, updated_at)"
    ),
    "proposal_problems": "SELECT, INSERT, DELETE",
    "proposal_attachments": "SELECT, INSERT, DELETE, UPDATE (sha256, size_bytes, av_status, rerendered, updated_at)",
    "proposal_lsh_bands": "SELECT, INSERT, DELETE",
    "originality_checks": "SELECT, INSERT",
    "provenance_records": "SELECT",  # /verify; written by provenance_worker
    "transparency_roots": "SELECT",
    "attestations": "SELECT, INSERT",  # append-only
    "tags": "SELECT, INSERT, UPDATE (status, updated_at)",  # the developer may only withdraw (policy)
    "engagements": "SELECT",  # fixtures only until the Phase 3 state machine
    "disclosure_grants": (
        "SELECT, INSERT, UPDATE (status, counts_as_unlock, billing_month, granted_by, granted_at, revoked_at,"
        " revoked_by, updated_at)"
    ),
    "nda_acceptances": "SELECT, INSERT",  # append-only
    "legal_acceptances": "SELECT, INSERT",  # append-only
    "document_views": "SELECT, INSERT, UPDATE (duration_bucket)",
    "signal_events": "INSERT",  # read only by aggregate_worker
    "moderation_cases": "SELECT, INSERT, UPDATE (status, reasons, assigned_to, decided_by, decided_at, updated_at)",
    # The OTP columns change only through app_reissue_claim_otp() and app_confirm_claim_otp() (attempts never reset).
    # otp_hash is written (INSERT) but never readable: codes are compared in SQL, so a read path (a query bug, an ORM
    # load) can never hand out a hash of a 6-digit code to brute-force offline.
    "org_claims": (
        "SELECT (id, org_id, claimant_user_id, domain, email_address, level, status, otp_expires_at, otp_attempts,"
        " otp_reissues, otp_verified_at, dns_token, dns_verified_at, registration_no, cr12_date, kra_pin,"
        " sector_register, public_entity_requested, document_keys, reviewed_by, decided_at, decision_reason,"
        " updated_at, created_at),"
        " INSERT, UPDATE (dns_token, dns_verified_at, registration_no, cr12_date, kra_pin, sector_register,"
        " public_entity_requested, document_keys, status, updated_at)"
    ),
    "directory_invitations": "SELECT, INSERT, UPDATE (status, reason, approved_by, sent_at, updated_at)",
    # Confirmed only through app_confirm_phone_otp(); otp_hash is written but never readable (as for org_claims).
    "phone_verifications": ("SELECT (id, user_id, phone_e164, attempts, expires_at, verified_at, created_at), INSERT"),
    "kyc_reviews": "SELECT, INSERT",  # decided only through app_decide_kyc()
    # inputs (sanitised Tier-1 values; Tier-2 fields only as name, tier and length: the LLM layer never stores Tier-2
    # plaintext, AC-SEC-6) is written but read only by staff admin, through app_llm_call_inputs().
    "llm_calls": (
        "SELECT (id, org_id, user_id, task, purpose, model, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_tokens, cost_usd, latency_ms, status, stop_reason, trace_id, created_at), INSERT"
    ),
}

# New column grants of bridge_app on revision 0001 tables (dropped with the column on downgrade).
APP_GRANTS_0001_TABLES: dict[str, str] = {"organizations": "UPDATE (county_code)"}
# users.subject_salt never leaves the database: bridge_app's table-wide SELECT of revision 0001 becomes a column SELECT
# of every other column (digests come from app_subject_digest()). Restored to the table-wide grant on downgrade.
USERS_READABLE_COLUMNS = (
    "id, email, email_verified_at, password_hash, display_name, locale, staff_role, status, totp_secret_enc,"
    " totp_pending_enc, totp_enabled_at, totp_last_counter, totp_recovery_hashes, updated_at, created_at"
)

# Privileges of the other roles on this revision's tables.
ROLE_GRANTS: dict[str, dict[str, str]] = {
    "tier2_reader": {
        "proposal_confidential": "SELECT, INSERT, UPDATE (ciphertext, nonce, wrapped_dek, kms_key_id, updated_at)"
    },
    "provenance_worker": {
        "proposal_versions": "SELECT, UPDATE (content_hash, prev_version_hash, manifest_version, updated_at)",
        "proposal_confidential": "SELECT, UPDATE (manifest_ciphertext, manifest_nonce, updated_at)",
        "provenance_records": (
            "SELECT, INSERT, UPDATE (signature, key_id, status, tsa_token, tsa_time, tsa_serial, tsa_url, ots_proof,"
            " evidence_s3_key)"
        ),
        "provenance_keys": "SELECT",
        "chain_anchors": "INSERT",
        "transparency_roots": "INSERT",
    },
    "tier2_embed_worker": {"proposal_confidential": "SELECT", "proposal_confidential_embeddings": "INSERT"},
    "tier2_moderation": {"proposal_confidential": "SELECT", "proposal_confidential_embeddings": "SELECT"},
    "dsr_exporter": {"proposal_confidential": "SELECT"},
    "aggregate_worker": {"signal_events": "SELECT"},
    "audit_reader": {"chain_anchors": "SELECT"},
}


# Generated-column and CHECK expressions of the tables below, verbatim from the ORM models.
SEARCH_TSV = (
    "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, coalesce(problem_statement, '')), 'B') || "
    "setweight(to_tsvector('simple'::regconfig, coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('simple'::regconfig, coalesce(impact_claims, '')), 'C')"
)
REGISTERED_IS_COMPLETE = (
    "status = 'draft' OR (title IS NOT NULL AND niche_id IS NOT NULL AND maturity IS NOT NULL AND ask IS "
    "NOT NULL AND problem_statement IS NOT NULL AND summary IS NOT NULL AND owner_handle IS NOT NULL AND "
    "cert_id IS NOT NULL AND registered_at IS NOT NULL)"
)
END_REASON_MATCHES_STATE = (
    "(state = 'DECLINED' AND end_reason IN ('NOT_PRIORITY', 'ALREADY_IN_PROGRESS_INTERNALLY', 'BUDGET', "
    "'NOT_RELEVANT', 'NEEDS_MATURITY', 'OTHER', 'BY_DEVELOPER')) OR (state = 'EXPIRED' AND end_reason IN "
    "('NO_REVIEW', 'NO_DECISION', 'CONTACT_NOT_MADE', 'NO_DEV_RESPONSE')) OR (state NOT IN ('DECLINED', "
    "'EXPIRED') AND end_reason IS NULL)"
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


# Predicates (0001's, plus staff and publication rules).
_SIGNED_IN = "app_user_id() IS NOT NULL"
_STAFF = "app_is_staff('{admin,moderator}')"
_STAFF_ADMIN = "app_is_staff('{admin}')"
_ORG_MEMBER = "app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id())"
# Members who may write an organisation's Briefs and brief invitations (not finance or viewer).
_ORG_EDITOR = "app_is_member(org_id, '{owner,admin,signatory,reviewer}')"
_LISTED = "verification IN ('unclaimed', 'e1', 'e2') AND delisted_at IS NULL"
_OPEN_CLAIM = "status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed')"
_PROPOSAL_OWNED = "EXISTS (SELECT 1 FROM proposals p WHERE p.id = {t}.proposal_id AND p.owner_id = app_user_id())"
_DRAFT_VERSION_OWNED = (
    "EXISTS (SELECT 1 FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id"
    " WHERE v.id = {t}.{col} AND v.status = 'draft' AND p.owner_id = app_user_id())"
)
_PROBLEM_WRITER = (
    "((org_id IS NULL AND created_by = app_user_id())"
    " OR (org_id IS NOT NULL AND app_is_member(org_id, '{owner,admin,signatory,reviewer}')))"
)

# Sources are added and removed by whoever may write the (non-candidate) problem.
_SOURCE_WRITER = (
    "EXISTS (SELECT 1 FROM problems p WHERE p.id = problem_sources.problem_id AND p.status <> 'candidate'"
    " AND ((p.org_id IS NULL AND p.created_by = app_user_id())"
    " OR (p.org_id IS NOT NULL AND app_is_member(p.org_id, '{owner,admin,signatory,reviewer}'))))"
)


def _user(table: str, commands: Sequence[str], column: str = "user_id") -> list[Policy]:
    own = f"{column} = app_user_id()"
    return [
        Policy(table, c, None if c == "INSERT" else own, own if c in ("INSERT", "UPDATE") else None) for c in commands
    ]


POLICIES: tuple[Policy, ...] = (
    # --- revision 0001 tables: the directory (every signed-in user reads listed organisations and their niches) ---
    Policy("organizations", "SELECT", f"{_SIGNED_IN} AND {_LISTED}", suffix="listed"),
    Policy(
        "org_niches",
        "SELECT",
        f"{_SIGNED_IN} AND EXISTS (SELECT 1 FROM organizations o WHERE o.id = org_niches.org_id"
        " AND o.verification IN ('unclaimed', 'e1', 'e2') AND o.delisted_at IS NULL)",
        suffix="listed",
    ),
    # --- problems (PUBLISHED): candidates are staff-only; an org Brief's problem follows the Brief's visibility ---
    Policy(
        "problems",
        "SELECT",
        "(status <> 'candidate' AND (created_by = app_user_id() OR (org_id IS NOT NULL AND app_is_member(org_id))))"
        f" OR ({_SIGNED_IN} AND status = 'published' AND moderation_state = 'clear'"
        " AND (org_id IS NULL OR EXISTS (SELECT 1 FROM problem_briefs b WHERE b.problem_id = problems.id)))"
        f" OR {_STAFF}",
    ),
    # Developer problems may publish at once (moderated after publishing); Briefs wait for review. Research-agent
    # candidates are not the app role's to create.
    Policy(
        "problems",
        "INSERT",
        check="created_by = app_user_id() AND moderator_id IS NULL AND moderation_state IN ('clear', 'held')"
        " AND ((source = 'developer' AND org_id IS NULL AND status IN ('published', 'pending_review'))"
        " OR (source = 'org_brief' AND org_id IS NOT NULL AND status = 'pending_review'"
        " AND app_is_member(org_id, '{owner,admin,signatory,reviewer}')))",
    ),
    Policy("problems", "UPDATE", _PROBLEM_WRITER, _PROBLEM_WRITER),
    Policy("problem_sources", "SELECT", "EXISTS (SELECT 1 FROM problems p WHERE p.id = problem_sources.problem_id)"),
    Policy("problem_sources", "INSERT", check=_SOURCE_WRITER),
    Policy("problem_sources", "DELETE", _SOURCE_WRITER),
    # --- problem_briefs (ORG + public read) and brief_invitations ---
    Policy(
        "problem_briefs",
        "SELECT",
        f"({_SIGNED_IN} AND visibility = 'public' AND status = 'published') OR ({_ORG_MEMBER})"
        " OR (status = 'published' AND EXISTS (SELECT 1 FROM brief_invitations i"
        " WHERE i.brief_id = problem_briefs.problem_id AND i.user_id = app_user_id()))"
        f" OR {_STAFF}",
    ),
    # Only E2 organisations publish Briefs (docs/spec/06 6.2; E1 cannot).
    Policy(
        "problem_briefs",
        "INSERT",
        check=f"{_ORG_EDITOR} AND (status <> 'published' OR EXISTS (SELECT 1 FROM organizations o"
        " WHERE o.id = problem_briefs.org_id AND o.verification = 'e2'))",
    ),
    Policy(
        "problem_briefs",
        "UPDATE",
        _ORG_EDITOR,
        f"{_ORG_EDITOR} AND (status <> 'published' OR EXISTS (SELECT 1 FROM organizations o"
        " WHERE o.id = problem_briefs.org_id AND o.verification = 'e2'))",
    ),
    Policy("brief_invitations", "SELECT", f"user_id = app_user_id() OR ({_ORG_MEMBER})"),
    Policy("brief_invitations", "INSERT", check=_ORG_EDITOR),
    Policy("brief_invitations", "DELETE", _ORG_EDITOR),
    # --- proposals (PUBLISHED) ---
    Policy(
        "proposals",
        "SELECT",
        f"owner_id = app_user_id() OR ({_SIGNED_IN} AND status = 'published' AND moderation_state = 'clear')"
        f" OR {_STAFF}",
    ),
    Policy("proposals", "INSERT", check="owner_id = app_user_id() AND moderation_state IN ('clear', 'held')"),
    Policy("proposals", "UPDATE", "owner_id = app_user_id()", "owner_id = app_user_id()"),
    # Drafts that were never registered may be removed; a registered proposal is hidden instead (AC-IP-6).
    Policy("proposals", "DELETE", "owner_id = app_user_id() AND status = 'draft' AND current_version_id IS NULL"),
    Policy(
        "proposal_versions",
        "SELECT",
        "EXISTS (SELECT 1 FROM proposals p WHERE p.id = proposal_versions.proposal_id"
        " AND (p.owner_id = app_user_id() OR proposal_versions.status = 'registered'))"
        f" OR {_STAFF}",
    ),
    Policy(
        "proposal_versions",
        "INSERT",
        check=f"status = 'draft' AND {_PROPOSAL_OWNED.format(t='proposal_versions')}",
    ),
    Policy(
        "proposal_versions",
        "UPDATE",
        _PROPOSAL_OWNED.format(t="proposal_versions"),
        _PROPOSAL_OWNED.format(t="proposal_versions"),
    ),
    Policy("proposal_versions", "DELETE", f"status = 'draft' AND {_PROPOSAL_OWNED.format(t='proposal_versions')}"),
    # The registration job fills the hashes of its owner's registered versions (one tenant per job).
    Policy("proposal_versions", "SELECT", "status = 'registered' AND app_owns_version(id)", role="provenance_worker"),
    Policy(
        "proposal_versions",
        "UPDATE",
        "status = 'registered' AND app_owns_version(id)",
        "app_owns_version(id)",
        role="provenance_worker",
    ),
    Policy(
        "proposal_problems",
        "SELECT",
        "EXISTS (SELECT 1 FROM proposal_versions v WHERE v.id = proposal_problems.proposal_version_id)",
    ),
    Policy(
        "proposal_problems",
        "INSERT",
        check=_DRAFT_VERSION_OWNED.format(t="proposal_problems", col="proposal_version_id")
        + " AND EXISTS (SELECT 1 FROM problems pr WHERE pr.id = proposal_problems.problem_id)",
    ),
    Policy(
        "proposal_problems", "DELETE", _DRAFT_VERSION_OWNED.format(t="proposal_problems", col="proposal_version_id")
    ),
    # --- Tier 2: no bridge_app policy (no privilege); one policy per role and command ---
    Policy(
        "proposal_confidential",
        "SELECT",
        "owner_id = app_user_id() OR app_tier2_granted(proposal_id, version_id)",
        role="tier2_reader",
    ),
    Policy("proposal_confidential", "INSERT", check="owner_id = app_user_id()", role="tier2_reader"),
    Policy(
        "proposal_confidential", "UPDATE", "owner_id = app_user_id()", "owner_id = app_user_id()", role="tier2_reader"
    ),
    Policy("proposal_confidential", "SELECT", "owner_id = app_user_id()", role="provenance_worker"),
    Policy(
        "proposal_confidential",
        "UPDATE",
        "owner_id = app_user_id()",
        "owner_id = app_user_id()",
        role="provenance_worker",
    ),
    Policy("proposal_confidential", "SELECT", "owner_id = app_user_id()", role="tier2_embed_worker"),
    Policy("proposal_confidential", "SELECT", _STAFF, role="tier2_moderation"),
    Policy("proposal_confidential", "SELECT", "owner_id = app_user_id()", role="dsr_exporter"),
    Policy("proposal_confidential_embeddings", "SELECT", _STAFF, role="tier2_moderation"),
    Policy(
        "proposal_confidential_embeddings",
        "INSERT",
        check="EXISTS (SELECT 1 FROM proposal_confidential c"
        " WHERE c.version_id = proposal_confidential_embeddings.version_id AND c.owner_id = app_user_id())",
        role="tier2_embed_worker",
    ),
    # --- provenance_records (EVIDENCE): public to readers (/verify is anonymous); the registration job, bound to the
    # owner (one tenant per job), reads and writes only the records of that owner's versions ---
    Policy("provenance_records", "SELECT", "true"),
    Policy("provenance_records", "SELECT", "app_owns_version(version_id)", role="provenance_worker"),
    Policy("provenance_records", "INSERT", check="app_owns_version(version_id)", role="provenance_worker"),
    Policy(
        "provenance_records",
        "UPDATE",
        "app_owns_version(version_id)",
        "app_owns_version(version_id)",
        role="provenance_worker",
    ),
    # --- user tables ---
    Policy("proposal_attachments", "SELECT", "owner_id = app_user_id()"),
    Policy(
        "proposal_attachments",
        "INSERT",
        check="owner_id = app_user_id() AND " + _DRAFT_VERSION_OWNED.format(t="proposal_attachments", col="version_id"),
    ),
    Policy("proposal_attachments", "UPDATE", "owner_id = app_user_id()", "owner_id = app_user_id()"),
    Policy(
        "proposal_attachments",
        "DELETE",
        "owner_id = app_user_id() AND " + _DRAFT_VERSION_OWNED.format(t="proposal_attachments", col="version_id"),
    ),
    *_user("originality_checks", ("SELECT", "INSERT")),
    Policy("attestations", "SELECT", "user_id = app_user_id()"),
    Policy(
        "attestations",
        "INSERT",
        check="user_id = app_user_id() AND EXISTS (SELECT 1 FROM proposal_versions v JOIN proposals p"
        " ON p.id = v.proposal_id WHERE v.id = attestations.version_id AND p.owner_id = app_user_id())",
    ),
    Policy("phone_verifications", "SELECT", "user_id = app_user_id()"),
    Policy(
        "phone_verifications",
        "INSERT",
        check="user_id = app_user_id() AND attempts = 0 AND verified_at IS NULL",
    ),
    Policy("kyc_reviews", "SELECT", f"user_id = app_user_id() OR {_STAFF_ADMIN}"),
    Policy(
        "kyc_reviews",
        "INSERT",
        check="user_id = app_user_id() AND status = 'submitted' AND verified_legal_name IS NULL"
        " AND is_adult IS NULL AND decided_by IS NULL AND decided_at IS NULL AND purge_due_at IS NULL"
        " AND images_purged_at IS NULL",
    ),
    # --- org_or_user tables ---
    # Tags: the developer; the organisation's members only once delivered. A new tag is open and its status must
    # match the organisation's verification (E2 delivered, E1 held_pending_verification, E0 held_unclaimed); the
    # developer may only withdraw (which closes the tag, tags_guard()); closing otherwise is app_close_tag()'s.
    Policy("tags", "SELECT", f"developer_id = app_user_id() OR (status = 'delivered' AND {_ORG_MEMBER})"),
    Policy(
        "tags",
        "INSERT",
        check="developer_id = app_user_id() AND closed_at IS NULL AND "
        + _PROPOSAL_OWNED.format(t="tags")
        + " AND EXISTS (SELECT 1 FROM organizations o WHERE o.id = tags.org_id AND o.delisted_at IS NULL"
        " AND ((o.verification = 'e2' AND tags.status = 'delivered')"
        " OR (o.verification = 'e1' AND tags.status = 'held_pending_verification')"
        " OR (o.verification = 'unclaimed' AND tags.status = 'held_unclaimed')))",
    ),
    Policy("tags", "UPDATE", "developer_id = app_user_id()", "developer_id = app_user_id() AND status = 'withdrawn'"),
    Policy("engagements", "SELECT", f"developer_id = app_user_id() OR ({_ORG_MEMBER})"),
    Policy("disclosure_grants", "SELECT", f"owner_id = app_user_id() OR ({_ORG_MEMBER})"),
    # The owner grants; a member of the organisation may only request (the owner then activates or denies).
    Policy(
        "disclosure_grants",
        "INSERT",
        check="(owner_id = app_user_id() AND "
        + _PROPOSAL_OWNED.format(t="disclosure_grants")
        + ") OR (status = 'requested' AND requested_by = app_user_id() AND granted_by IS NULL"
        " AND app_is_member(org_id, '{owner,admin,reviewer,signatory}') AND EXISTS (SELECT 1 FROM proposals p"
        " WHERE p.id = disclosure_grants.proposal_id AND p.owner_id = disclosure_grants.owner_id))",
    ),
    Policy("disclosure_grants", "UPDATE", "owner_id = app_user_id()", "owner_id = app_user_id()"),
    Policy("nda_acceptances", "SELECT", f"user_id = app_user_id() OR ({_ORG_MEMBER})"),
    Policy(
        "nda_acceptances",
        "INSERT",
        check="user_id = app_user_id() AND app_is_member(org_id)"
        " AND EXISTS (SELECT 1 FROM proposals p WHERE p.id = nda_acceptances.proposal_id)",
    ),
    Policy("legal_acceptances", "SELECT", _ORG_MEMBER),
    # By the organisation's owner, admin or signatory; or the Master Enterprise Terms by the claimant of their own open
    # E2 claim whose email code is verified, on an organisation that is not E2 yet (docs/spec/06 6.2: the E2 review
    # includes the e-signed terms, before the claimant is a member). Which acceptances count is decided in SQL by
    # app_decide_claim() and app_tier2_granted(): the current version, by the approved E2 claimant or a signatory.
    Policy(
        "legal_acceptances",
        "INSERT",
        check="user_id = app_user_id() AND (app_is_member(org_id, '{owner,admin,signatory}')"
        " OR (EXISTS (SELECT 1 FROM org_claims c WHERE c.org_id = legal_acceptances.org_id"
        f" AND c.claimant_user_id = app_user_id() AND c.level = 'e2' AND c.{_OPEN_CLAIM}"
        " AND c.otp_verified_at IS NOT NULL)"
        " AND EXISTS (SELECT 1 FROM organizations o WHERE o.id = legal_acceptances.org_id"
        " AND o.verification IN ('unclaimed', 'e1'))"
        " AND EXISTS (SELECT 1 FROM legal_templates t WHERE t.id = legal_acceptances.legal_template_id"
        " AND t.kind = 'master_enterprise_terms')))",
    ),
    Policy("document_views", "SELECT", "owner_id = app_user_id() OR viewer_user_id = app_user_id()"),
    Policy(
        "document_views",
        "INSERT",
        check="viewer_user_id = app_user_id() AND app_is_member(org_id)"
        " AND EXISTS (SELECT 1 FROM proposals p WHERE p.id = document_views.proposal_id"
        " AND p.owner_id = document_views.owner_id)"
        " AND (nda_acceptance_id IS NULL OR EXISTS (SELECT 1 FROM nda_acceptances n"
        " WHERE n.id = document_views.nda_acceptance_id AND n.user_id = app_user_id()))",
    ),
    Policy("document_views", "UPDATE", "viewer_user_id = app_user_id()", "viewer_user_id = app_user_id()"),
    Policy(
        "org_claims",
        "SELECT",
        "claimant_user_id = app_user_id() OR (app_is_member(org_id, '{owner,admin}')"
        f" AND (app_org_id() IS NULL OR org_id = app_org_id())) OR {_STAFF}",
    ),
    Policy(
        "org_claims",
        "INSERT",
        check=f"claimant_user_id = app_user_id() AND {_OPEN_CLAIM} AND otp_attempts = 0 AND otp_reissues = 0"
        " AND (otp_expires_at IS NULL OR otp_expires_at <= now() + interval '1 hour')"
        " AND otp_verified_at IS NULL AND dns_verified_at IS NULL AND reviewed_by IS NULL AND decided_at IS NULL"
        " AND CAST(split_part(CAST(email_address AS text), '@', 2) AS citext) = domain",
    ),
    # The claimant moves an open claim along or withdraws it; approval and rejection are the definer functions'.
    Policy(
        "org_claims",
        "UPDATE",
        f"claimant_user_id = app_user_id() AND {_OPEN_CLAIM}",
        "claimant_user_id = app_user_id()"
        " AND status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed', 'withdrawn')",
    ),
    Policy(
        "llm_calls",
        "SELECT",
        f"user_id = app_user_id() OR (org_id IS NOT NULL AND {_ORG_MEMBER}) OR {_STAFF_ADMIN}",
    ),
    # System rows (no user, no organisation) are allowed; a row never names another user or a foreign organisation.
    Policy(
        "llm_calls",
        "INSERT",
        check="(user_id IS NULL OR user_id = app_user_id()) AND (org_id IS NULL OR app_is_member(org_id))",
    ),
    # --- staff tables ---
    Policy("moderation_cases", "SELECT", _STAFF),
    Policy(
        "moderation_cases",
        "INSERT",
        check="(reporter_id IS NULL OR reporter_id = app_user_id()) AND status IN ('open', 'held')"
        " AND assigned_to IS NULL AND decided_by IS NULL AND decided_at IS NULL",
    ),
    Policy("moderation_cases", "UPDATE", _STAFF, f"{_STAFF} AND (decided_by IS NULL OR decided_by = app_user_id())"),
    Policy("directory_invitations", "SELECT", _STAFF_ADMIN),
    Policy(
        "directory_invitations",
        "INSERT",
        check="status = 'proposed' AND approved_by IS NULL AND sent_at IS NULL"
        " AND (proposed_by IS NULL OR proposed_by = app_user_id())",
    ),
    Policy(
        "directory_invitations",
        "UPDATE",
        _STAFF_ADMIN,
        f"{_STAFF_ADMIN} AND (approved_by IS NULL OR approved_by = app_user_id())",
    ),
)

# The roles and schema USAGE this revision grants to live in infra/postgres (bridge_owner cannot create roles).
PREFLIGHT_SQL = r"""
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['tier2_reader', 'provenance_worker', 'tier2_embed_worker', 'tier2_moderation',
                             'dsr_exporter']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = r) THEN
            RAISE EXCEPTION 'revision 0002: role % is missing; run infra/postgres/roles.sql as a superuser first', r;
        END IF;
        IF NOT pg_catalog.has_schema_privilege(r, 'public', 'USAGE') THEN
            RAISE EXCEPTION 'revision 0002: role % has no USAGE on schema public; run infra/postgres/prepare_db.sql', r;
        END IF;
    END LOOP;
END
$$;
"""

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last), EXECUTE is
# revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS). SECURITY DEFINER functions run as bridge_owner, which
# bypasses RLS (ENABLED, not FORCED), and check their caller in SQL before changing anything.
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- True when the current user (app.user_id) is active platform staff with TOTP enrolled, holding any of p_roles (any
-- staff role when NULL). SECURITY DEFINER so roles without a grant on users (tier2_moderation) can call it.
CREATE FUNCTION app_is_staff(p_roles staff_role[] DEFAULT NULL) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.users u
         WHERE u.id = public.app_user_id()
           AND u.staff_role IS NOT NULL
           AND u.status = 'active'
           AND u.totp_enabled_at IS NOT NULL
           AND (p_roles IS NULL OR u.staff_role = ANY (p_roles))
    )
$$;

-- True when p_version is a version of a proposal the current user (app.user_id) owns. SECURITY DEFINER: the policies of
-- provenance_worker call it, and that role cannot read proposals.
CREATE FUNCTION app_owns_version(p_version uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.proposal_versions v
          JOIN public.proposals p ON p.id = v.proposal_id
         WHERE v.id = p_version AND p.owner_id = public.app_user_id()
    )
$$;

-- The current version of a legal template kind: the most recently created one. Publishing a new version supersedes
-- the old: acceptances of a superseded version no longer count (app_decide_claim, app_tier2_granted).
CREATE FUNCTION app_current_legal_template(p_kind legal_template_kind) RETURNS uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT t.id FROM public.legal_templates t WHERE t.kind = p_kind ORDER BY t.created_at DESC, t.id DESC LIMIT 1
$$;

-- The database half of can_view_tier2 (docs/spec/06 6.1), used by the tier2_reader SELECT policy: the current user may
-- read Tier 2 of p_version through an organisation when all of these hold. The application predicate checks the rest
-- (FEATURE_TIER2_ENABLED, step-up recency) and is the one that answers 403 with the failing condition. The viewer's
-- membership must be on the organisation's verified domain (their email address at exactly that domain). The Master
-- Enterprise Terms count only in their current version and only when accepted by the organisation's approved E2
-- claimant or by an active signatory (never by any other member or an outsider).
CREATE FUNCTION app_tier2_granted(p_proposal uuid, p_version uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.disclosure_grants g
          JOIN public.proposals p ON p.id = g.proposal_id
          JOIN public.proposal_versions v ON v.proposal_id = g.proposal_id
          JOIN public.organizations o ON o.id = g.org_id
          JOIN public.memberships m ON m.org_id = g.org_id
          JOIN public.users u ON u.id = m.user_id
         WHERE g.proposal_id = p_proposal
           AND v.id = p_version
           AND v.status = 'registered'                                -- drafts are Tier 0: owner only
           AND p.status = 'published' AND p.moderation_state = 'clear'  -- hidden ("deleted") or held: no new views
           AND g.status = 'active' AND g.tier >= 2 AND g.revoked_at IS NULL
           AND (public.app_org_id() IS NULL OR g.org_id = public.app_org_id())
           AND o.verification = 'e2' AND o.suspended_at IS NULL AND o.verified_domain IS NOT NULL
           AND m.user_id = public.app_user_id() AND m.status = 'active'
           AND m.roles && '{reviewer,signatory,admin}'::public.org_role[]
           AND u.status = 'active' AND u.totp_enabled_at IS NOT NULL
           -- membership on the verified domain: the member's email address is at exactly that domain
           AND CAST(split_part(CAST(u.email AS text), '@', 2) AS public.citext) = o.verified_domain
           AND EXISTS (
                SELECT 1
                  FROM public.legal_acceptances la
                 WHERE la.org_id = g.org_id
                   AND la.legal_template_id = public.app_current_legal_template('master_enterprise_terms')
                   AND (EXISTS (
                            SELECT 1
                              FROM public.org_claims c
                             WHERE c.org_id = la.org_id AND c.claimant_user_id = la.user_id
                               AND c.level = 'e2' AND c.status = 'approved')
                        OR EXISTS (
                            SELECT 1
                              FROM public.memberships s
                             WHERE s.org_id = la.org_id AND s.user_id = la.user_id AND s.status = 'active'
                               AND s.roles && '{signatory}'::public.org_role[])))
           AND EXISTS (
                SELECT 1
                  FROM public.nda_acceptances na
                  JOIN public.nda_templates nt ON nt.id = na.nda_template_id
                 WHERE na.user_id = m.user_id AND na.org_id = g.org_id AND na.proposal_id = g.proposal_id
                   AND nt.kind = 'evaluation')
           AND NOT EXISTS (
                SELECT 1
                  FROM public.engagements e
                 WHERE e.proposal_id = g.proposal_id AND e.org_id = g.org_id
                   AND e.state IN ('WITHDRAWN', 'DECLINED', 'TERMINATED'))
    )
$$;

-- SHA-256(subject_salt || p_data) for one user: owner refs in manifests (p_data = the id's 16 bytes, uuid_send(id)) and
-- the per-subject salted digests of personal or free text in audit payloads (docs/spec/06 6.4 items 1 and 4). The salt
-- itself never leaves the database (bridge_app holds no SELECT on users.subject_salt). NULL for an unknown user.
CREATE FUNCTION app_subject_digest(p_user_id uuid, p_data bytea) RETURNS bytea
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT pg_catalog.sha256(u.subject_salt || p_data) FROM public.users u WHERE u.id = p_user_id
$$;

-- An E1 organisation sees only how many tags are held for it (docs/spec/06 6.3); members only, 0 for anyone else.
CREATE FUNCTION app_held_tag_count(p_org uuid) RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CASE
               WHEN public.app_is_member(p_org) THEN (
                   SELECT count(*)::integer
                     FROM public.tags t
                    WHERE t.org_id = p_org AND t.closed_at IS NULL
                      AND t.status IN ('held_unclaimed', 'held_pending_verification'))
               ELSE 0
           END
$$;

-- D1 (docs/spec/06 6.4 item 8): compares the stored OTP hash for one of the caller's codes, counts the attempt (at most
-- 5, until expiry) and on a match marks the code verified and raises the profile from D0 to D1. Only a D0 profile can
-- match: once the account is D1 (or without a developer profile) every attempt is counted and fails, so a second open
-- code for another number never verifies too. Returns whether this call matched. The caller must commit even when it
-- returns false, or the attempt is not counted.
CREATE FUNCTION app_confirm_phone_otp(p_verification uuid, p_otp_hash bytea) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_row public.phone_verifications%ROWTYPE;
    v_level public.dev_verification;
    v_match boolean;
BEGIN
    SELECT * INTO v_row
      FROM public.phone_verifications
     WHERE id = p_verification AND user_id = v_user
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_confirm_phone_otp: no such code for the current user'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_row.verified_at IS NOT NULL OR v_row.expires_at <= now() OR v_row.attempts >= 5 THEN
        RETURN false;
    END IF;
    SELECT verification_level INTO v_level FROM public.developer_profiles WHERE user_id = v_user FOR UPDATE;
    v_match := coalesce(v_level = 'd0', false) AND p_otp_hash IS NOT NULL AND v_row.otp_hash = p_otp_hash;
    UPDATE public.phone_verifications
       SET attempts = attempts + 1,
           verified_at = CASE WHEN v_match THEN now() END
     WHERE id = v_row.id;
    IF v_match THEN
        UPDATE public.developer_profiles
           SET verification_level = 'd1', updated_at = now()
         WHERE user_id = v_user AND verification_level = 'd0';
    END IF;
    RETURN v_match;
END;
$$;

-- D2 (ManualReview by staff admin): records the outcome and schedules the image purge 72 h later. Approval needs the
-- legal name, ID type, last four characters and an adult subject who is already D1, and raises D1 to D2. Staff never
-- decide their own review.
CREATE FUNCTION app_decide_kyc(
    p_review uuid, p_approve boolean, p_reference text, p_legal_name text, p_id_type text, p_id_last4 text,
    p_is_adult boolean
) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_staff uuid := public.app_user_id();
    v_review public.kyc_reviews%ROWTYPE;
    v_level public.dev_verification;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_decide_kyc: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_review FROM public.kyc_reviews WHERE id = p_review FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_decide_kyc: no such review' USING ERRCODE = 'no_data_found';
    END IF;
    IF v_review.user_id = v_staff THEN
        RAISE EXCEPTION 'app_decide_kyc: staff cannot decide their own review' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_review.status <> 'submitted' THEN
        RAISE EXCEPTION 'app_decide_kyc: the review is already decided' USING ERRCODE = 'check_violation';
    END IF;
    IF p_approve THEN
        IF p_is_adult IS NOT TRUE OR coalesce(btrim(p_legal_name), '') = '' OR coalesce(btrim(p_id_type), '') = ''
           OR p_id_last4 IS NULL THEN
            RAISE EXCEPTION 'app_decide_kyc: approval needs the legal name, ID type, last four characters and an adult'
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT verification_level INTO v_level
          FROM public.developer_profiles
         WHERE user_id = v_review.user_id
           FOR UPDATE;
        IF v_level IS NULL OR v_level = 'd0' THEN
            RAISE EXCEPTION 'app_decide_kyc: D2 needs a D1 (phone-verified) developer'
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_level = 'd1' THEN
            UPDATE public.developer_profiles
               SET verification_level = 'd2', updated_at = now()
             WHERE user_id = v_review.user_id;
        END IF;
    END IF;
    UPDATE public.kyc_reviews
       SET status = CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END::public.kyc_status,
           reference = coalesce(p_reference, reference),
           verified_legal_name = CASE WHEN p_approve THEN btrim(p_legal_name) END,
           id_type = p_id_type,
           id_last4 = p_id_last4,
           is_adult = p_is_adult,
           decided_by = v_staff,
           decided_at = now(),
           purge_due_at = now() + interval '72 hours',
           updated_at = now()
     WHERE id = p_review;
END;
$$;

-- The kyc.purge job (no tenant context): reviews whose ID images are due for deletion, then the bookkeeping once the
-- objects are gone. Only ids leave the function.
CREATE FUNCTION app_kyc_purge_due() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT r.id
      FROM public.kyc_reviews r
     WHERE r.decided_at IS NOT NULL AND r.images_purged_at IS NULL AND r.purge_due_at <= now()
     ORDER BY r.purge_due_at
$$;

CREATE FUNCTION app_mark_kyc_images_purged(p_review uuid) RETURNS boolean
    LANGUAGE sql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    WITH marked AS (
        UPDATE public.kyc_reviews
           SET images_purged_at = now(), updated_at = now()
         WHERE id = p_review AND decided_at IS NOT NULL AND images_purged_at IS NULL AND purge_due_at <= now()
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM marked)
$$;

-- Moderation decisions (staff admin or moderator, never on their own content).
CREATE FUNCTION app_moderate_proposal(p_proposal uuid, p_state moderation_state) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_moderate_proposal: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.proposals
       SET moderation_state = p_state, updated_at = now()
     WHERE id = p_proposal AND owner_id <> public.app_user_id();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_moderate_proposal: no such proposal, or it is the moderator''s own'
            USING ERRCODE = 'no_data_found';
    END IF;
END;
$$;

CREATE FUNCTION app_moderate_problem(p_problem uuid, p_state moderation_state, p_status problem_status) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_moderate_problem: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.problems
       SET moderation_state = p_state,
           status = p_status,
           moderator_id = public.app_user_id(),
           published_at = CASE WHEN p_status = 'published' THEN coalesce(published_at, now()) ELSE published_at END,
           updated_at = now()
     WHERE id = p_problem AND created_by IS DISTINCT FROM public.app_user_id();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_moderate_problem: no such problem, or it is the moderator''s own'
            USING ERRCODE = 'no_data_found';
    END IF;
END;
$$;

-- Raising a hold (clear -> held) is the only moderation change the owner's side may make (REQ-PROP-02: a flagged teaser
-- is held until a moderator approves it). Owner or staff only; held and rejected stay as they are. The checks are
-- NULL-safe: without app.user_id a plain comparison would be NULL, which IF treats as false, and skip the RAISE.
CREATE FUNCTION app_hold_proposal(p_proposal uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_owner uuid;
BEGIN
    SELECT owner_id INTO v_owner FROM public.proposals WHERE id = p_proposal FOR UPDATE;
    IF v_owner IS NULL OR public.app_user_id() IS NULL
       OR (v_owner IS DISTINCT FROM public.app_user_id() AND NOT public.app_is_staff('{admin,moderator}')) THEN
        RAISE EXCEPTION 'app_hold_proposal: owner or staff only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.proposals
       SET moderation_state = 'held', updated_at = now()
     WHERE id = p_proposal AND moderation_state = 'clear';
END;
$$;

CREATE FUNCTION app_hold_problem(p_problem uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_problem public.problems%ROWTYPE;
BEGIN
    SELECT * INTO v_problem FROM public.problems WHERE id = p_problem FOR UPDATE;
    IF NOT FOUND OR public.app_user_id() IS NULL OR NOT coalesce(
        (v_problem.org_id IS NULL AND v_problem.created_by = public.app_user_id())
        OR (v_problem.org_id IS NOT NULL
            AND public.app_is_member(v_problem.org_id, '{owner,admin,signatory,reviewer}'))
        OR public.app_is_staff('{admin,moderator}'),
        false
    ) THEN
        RAISE EXCEPTION 'app_hold_problem: owner or staff only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.problems
       SET moderation_state = 'held', updated_at = now()
     WHERE id = p_problem AND moderation_state = 'clear';
END;
$$;

-- E1 domain-email OTP: compares the stored hash of the claimant's open claim (until expiry) and on a match sets
-- otp_verified_at, which the app cannot set. otp_attempts counts every attempt on the claim and is never reset; the
-- claim's budget is 5 attempts per code issued (the first plus at most 5 reissues, so at most 30). Returns whether
-- this call matched; commit either way.
CREATE FUNCTION app_confirm_claim_otp(p_claim uuid, p_otp_hash bytea) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_claim public.org_claims%ROWTYPE;
    v_match boolean;
BEGIN
    SELECT * INTO v_claim
      FROM public.org_claims
     WHERE id = p_claim AND claimant_user_id = public.app_user_id()
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_confirm_claim_otp: no such claim for the current user'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_claim.status NOT IN ('otp_sent', 'dns_pending') OR v_claim.otp_verified_at IS NOT NULL
       OR v_claim.otp_hash IS NULL OR v_claim.otp_expires_at IS NULL OR v_claim.otp_expires_at <= now()
       OR v_claim.otp_attempts >= 5 * (1 + v_claim.otp_reissues) THEN
        RETURN false;
    END IF;
    v_match := p_otp_hash IS NOT NULL AND v_claim.otp_hash = p_otp_hash;
    UPDATE public.org_claims
       SET otp_attempts = otp_attempts + 1,
           otp_verified_at = CASE WHEN v_match THEN now() END,
           updated_at = now()
     WHERE id = p_claim;
    RETURN v_match;
END;
$$;

-- A new email code for the claimant's open claim that is still waiting for one: replaces the hash and expiry (at most
-- an hour ahead) and counts the reissue; the attempt count carries on. After 5 reissues no code is issued: the claim
-- moves to manual review (pending_review) and the function returns false. A fresh claim on the same organisation is
-- only possible after the 24-hour cooldown of org_claims_guard(), so a new claim cannot reset the limits either.
CREATE FUNCTION app_reissue_claim_otp(p_claim uuid, p_otp_hash bytea, p_expires_at timestamptz) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_claim public.org_claims%ROWTYPE;
BEGIN
    SELECT * INTO v_claim
      FROM public.org_claims
     WHERE id = p_claim AND claimant_user_id = public.app_user_id()
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_reissue_claim_otp: no such claim for the current user'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_claim.status NOT IN ('otp_sent', 'dns_pending') OR v_claim.otp_verified_at IS NOT NULL THEN
        RAISE EXCEPTION 'app_reissue_claim_otp: the claim is not waiting for an email code'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_otp_hash IS NULL OR octet_length(p_otp_hash) <> 32 OR p_expires_at IS NULL OR p_expires_at <= now()
       OR p_expires_at > now() + interval '1 hour' THEN
        RAISE EXCEPTION 'app_reissue_claim_otp: a 32-byte code digest and an expiry within the next hour are required'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF v_claim.otp_reissues >= 5 THEN
        UPDATE public.org_claims SET status = 'pending_review', updated_at = now() WHERE id = p_claim;
        RETURN false;
    END IF;
    UPDATE public.org_claims
       SET otp_hash = p_otp_hash,
           otp_expires_at = p_expires_at,
           otp_reissues = otp_reissues + 1,
           updated_at = now()
     WHERE id = p_claim;
    RETURN true;
END;
$$;

-- Automatic E1 (docs/spec/06 6.2) for the claimant's own open E1 claim once the OTP and the DNS TXT record are
-- verified. Automatic only when the organisation is unclaimed or pending, not delisted, has no other open claim, and
-- the domain is in official_domains[] (or it is the claimant's own self-signup organisation); otherwise the claim goes
-- to manual review, and a claim on an E2 organisation becomes a dispute (never a transfer). On approval: verification
-- e1, verified_domain, the claimant's owner+admin membership, held_unclaimed tags -> held_pending_verification.
CREATE FUNCTION app_approve_claim_e1(p_claim uuid) RETURNS claim_status
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_claim public.org_claims%ROWTYPE;
    v_org public.organizations%ROWTYPE;
    v_status public.claim_status;
BEGIN
    SELECT * INTO v_claim
      FROM public.org_claims
     WHERE id = p_claim AND claimant_user_id = v_user
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_approve_claim_e1: no such claim for the current user'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_claim.level <> 'e1' OR v_claim.status NOT IN ('otp_sent', 'dns_pending') THEN
        RAISE EXCEPTION 'app_approve_claim_e1: not an open E1 claim' USING ERRCODE = 'check_violation';
    END IF;
    IF v_claim.otp_verified_at IS NULL OR v_claim.dns_verified_at IS NULL THEN
        RAISE EXCEPTION 'app_approve_claim_e1: the email OTP and the DNS TXT record must both be verified'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT * INTO v_org FROM public.organizations WHERE id = v_claim.org_id FOR UPDATE;
    IF v_org.verification = 'e2' THEN
        v_status := 'disputed';
    ELSIF v_org.verification IN ('unclaimed', 'pending')
          AND v_org.delisted_at IS NULL
          AND NOT EXISTS (
              SELECT 1
                FROM public.org_claims c
               WHERE c.org_id = v_org.id AND c.id <> v_claim.id
                 AND c.status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed'))
          AND ((v_org.source = 'self_signup' AND public.app_is_member(v_org.id, '{owner}'))
               OR v_claim.domain = ANY (v_org.official_domains)) THEN
        v_status := 'approved';
    ELSE
        v_status := 'pending_review';
    END IF;
    IF v_status = 'approved' THEN
        UPDATE public.organizations
           SET verification = 'e1', verified_domain = v_claim.domain, updated_at = now()
         WHERE id = v_org.id;
        INSERT INTO public.memberships AS m (id, org_id, user_id, roles, status)
        VALUES (public.uuid7(), v_org.id, v_user, '{owner,admin}', 'active')
        ON CONFLICT (org_id, user_id) DO UPDATE
           SET status = 'active',
               roles = ARRAY(SELECT DISTINCT x FROM unnest(m.roles || EXCLUDED.roles) AS x ORDER BY x),
               updated_at = now();
        UPDATE public.tags
           SET status = 'held_pending_verification', updated_at = now()
         WHERE org_id = v_org.id AND status = 'held_unclaimed' AND closed_at IS NULL;
    END IF;
    UPDATE public.org_claims
       SET status = v_status,
           decided_at = CASE WHEN v_status = 'approved' THEN now() END,
           updated_at = now()
     WHERE id = p_claim;
    RETURN v_status;
END;
$$;

-- Staff admin decision on an open claim (manual E1, E2 via ManualReviewVerifier, disputes). Approving E2 needs the
-- current Master Enterprise Terms accepted by this claimant; it sets e2, verified_domain, e2_verified_at, the annual
-- re-verification date, public_entity as requested, and delivers the organisation's held tags. Approval makes the
-- claimant an owner and admin. Every approval needs the claimed domain proven: the email code (otp_verified_at) and
-- the DNS TXT record (dns_verified_at), or, for E2 only, a claimant who is an active owner, admin or signatory of an
-- organisation already E1 on that same domain. Staff never decide their own claim.
CREATE FUNCTION app_decide_claim(p_claim uuid, p_approve boolean, p_reason text) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_staff uuid := public.app_user_id();
    v_claim public.org_claims%ROWTYPE;
    v_org public.organizations%ROWTYPE;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_decide_claim: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_claim FROM public.org_claims WHERE id = p_claim FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_decide_claim: no such claim' USING ERRCODE = 'no_data_found';
    END IF;
    IF v_claim.claimant_user_id = v_staff THEN
        RAISE EXCEPTION 'app_decide_claim: staff cannot decide their own claim'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_claim.status NOT IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed') THEN
        RAISE EXCEPTION 'app_decide_claim: the claim is not open' USING ERRCODE = 'check_violation';
    END IF;
    IF p_approve THEN
        SELECT * INTO v_org FROM public.organizations WHERE id = v_claim.org_id FOR UPDATE;
        IF NOT (
            (v_claim.otp_verified_at IS NOT NULL AND v_claim.dns_verified_at IS NOT NULL)
            OR (v_claim.level = 'e2' AND v_org.verification = 'e1' AND v_org.verified_domain = v_claim.domain
                AND EXISTS (
                    SELECT 1
                      FROM public.memberships m
                     WHERE m.org_id = v_org.id AND m.user_id = v_claim.claimant_user_id AND m.status = 'active'
                       AND m.roles && '{owner,admin,signatory}'::public.org_role[]))
        ) THEN
            RAISE EXCEPTION 'app_decide_claim: the claimed domain is not proven (email code and DNS TXT record, or for'
                ' E2 a member of the organisation already E1 on that domain)' USING ERRCODE = 'check_violation';
        END IF;
        IF v_claim.level = 'e1' THEN
            IF v_org.verification = 'e2' THEN
                RAISE EXCEPTION 'app_decide_claim: an E2 organisation is not moved back to E1'
                    USING ERRCODE = 'check_violation';
            END IF;
            UPDATE public.organizations
               SET verification = 'e1', verified_domain = v_claim.domain, updated_at = now()
             WHERE id = v_org.id;
            UPDATE public.tags
               SET status = 'held_pending_verification', updated_at = now()
             WHERE org_id = v_org.id AND status = 'held_unclaimed' AND closed_at IS NULL;
        ELSE
            IF NOT EXISTS (
                SELECT 1
                  FROM public.legal_acceptances la
                 WHERE la.org_id = v_org.id AND la.user_id = v_claim.claimant_user_id
                   AND la.legal_template_id = public.app_current_legal_template('master_enterprise_terms')
            ) THEN
                RAISE EXCEPTION 'app_decide_claim: E2 needs the current Master Enterprise Terms, accepted by the'
                    ' claimant'
                    USING ERRCODE = 'check_violation';
            END IF;
            UPDATE public.organizations
               SET verification = 'e2',
                   verified_domain = v_claim.domain,
                   e2_verified_at = now(),
                   reverify_due_on = ((now() AT TIME ZONE 'Africa/Nairobi') + interval '1 year')::date,
                   public_entity = v_claim.public_entity_requested,
                   registration_no = coalesce(v_claim.registration_no, registration_no),
                   updated_at = now()
             WHERE id = v_org.id;
            UPDATE public.tags
               SET status = 'delivered', updated_at = now()
             WHERE org_id = v_org.id AND status IN ('held_unclaimed', 'held_pending_verification')
               AND closed_at IS NULL;
        END IF;
        INSERT INTO public.memberships AS m (id, org_id, user_id, roles, status)
        VALUES (public.uuid7(), v_org.id, v_claim.claimant_user_id, '{owner,admin}', 'active')
        ON CONFLICT (org_id, user_id) DO UPDATE
           SET status = 'active',
               roles = ARRAY(SELECT DISTINCT x FROM unnest(m.roles || EXCLUDED.roles) AS x ORDER BY x),
               updated_at = now();
    END IF;
    UPDATE public.org_claims
       SET status = CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END::public.claim_status,
           reviewed_by = v_staff,
           decided_at = now(),
           decision_reason = p_reason,
           updated_at = now()
     WHERE id = p_claim;
END;
$$;

-- Delisting on request (docs/spec/06 6.2): E0 organisations only, by staff admin; held tags are released to the
-- developer (the app sends the notice).
CREATE FUNCTION app_delist_org(p_org uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_delist_org: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.organizations
       SET delisted_at = coalesce(delisted_at, now()), updated_at = now()
     WHERE id = p_org AND verification = 'unclaimed';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_delist_org: only an unclaimed (E0) organisation can be delisted'
            USING ERRCODE = 'check_violation';
    END IF;
    UPDATE public.tags
       SET status = 'released', updated_at = now()
     WHERE org_id = p_org AND status = 'held_unclaimed' AND closed_at IS NULL;
END;
$$;

-- RFC 8058 one-click unsubscribe from directory invitations: the endpoint has no signed-in user, so it verifies its
-- signed token and then records the opt-out here (the organisation is never invited again).
CREATE FUNCTION app_opt_out_org_invitations(p_invitation uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    UPDATE public.organizations o
       SET invitations_opted_out_at = coalesce(o.invitations_opted_out_at, now()), updated_at = now()
      FROM public.directory_invitations i
     WHERE i.id = p_invitation AND o.id = i.org_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_opt_out_org_invitations: no such invitation' USING ERRCODE = 'no_data_found';
    END IF;
END;
$$;

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

-- Chain heads for the hourly RFC 3161 anchor (provenance.anchor_chain_heads, REQ-AUD-01): the last event of every
-- audit chain. Only chain ids, sequence numbers and hashes leave the function (no actor, payload or details).
-- EXECUTE is provenance_worker's only, the role that writes chain_anchors.
CREATE FUNCTION app_audit_chain_heads() RETURNS TABLE (chain_id text, seq bigint, event_hash bytea)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT DISTINCT ON (e.chain_id) CAST(e.chain_id AS text), e.seq, e.event_hash
      FROM public.audit_events e
     ORDER BY e.chain_id, e.seq DESC
$$;

-- Adds a niche without a deploy (docs/spec/06 6.2, AC-DIR-5: an admin-added niche is selectable in the directory,
-- the editor and the scout form at once). Staff admin only. The slug is lower-case letters and digits joined by
-- hyphens and must be new; a child's parent must be an active top-level niche (the taxonomy has two levels). Returns
-- the new niche's id; the caller writes the audit event.
CREATE FUNCTION app_add_niche(
    p_slug text, p_name_en text, p_parent_slug text DEFAULT NULL, p_isic_code text DEFAULT NULL
) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_id uuid := public.uuid7();
    v_parent public.niches%ROWTYPE;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_add_niche: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_slug IS NULL OR length(p_slug) > 80 OR p_slug !~ '^[a-z0-9]+(-[a-z0-9]+)*$' THEN
        RAISE EXCEPTION 'app_add_niche: the slug is lower-case letters and digits joined by hyphens, at most 80'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF coalesce(btrim(p_name_en), '') = '' OR length(btrim(p_name_en)) > 120 THEN
        RAISE EXCEPTION 'app_add_niche: the English name is required, at most 120 characters'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_isic_code IS NOT NULL AND p_isic_code !~ '^[A-Z0-9]{1,8}$' THEN
        RAISE EXCEPTION 'app_add_niche: the ISIC code is 1 to 8 upper-case letters and digits'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_parent_slug IS NOT NULL THEN
        SELECT * INTO v_parent FROM public.niches WHERE slug = p_parent_slug;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'app_add_niche: no such parent niche' USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF v_parent.parent_id IS NOT NULL OR NOT v_parent.active THEN
            RAISE EXCEPTION 'app_add_niche: the parent must be an active top-level niche (two levels)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM public.niches n WHERE n.slug = p_slug) THEN
        RAISE EXCEPTION 'app_add_niche: the slug is taken' USING ERRCODE = 'unique_violation';
    END IF;
    INSERT INTO public.niches (id, slug, name_en, parent_id, isic_code)
    VALUES (v_id, p_slug, btrim(p_name_en), v_parent.id, p_isic_code);
    RETURN v_id;
END;
$$;

-- The sanitised inputs of one LLM call (kept 30 days), for staff admin only: bridge_app holds no SELECT on
-- llm_calls.inputs, so users and members read their call rows without them. NULL for an unknown call.
CREATE FUNCTION app_llm_call_inputs(p_call uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_llm_call_inputs: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN (SELECT c.inputs FROM public.llm_calls c WHERE c.id = p_call);
END;
$$;

-- The platform-wide LLM spend since p_since, for the global daily cap (docs/spec/09); an aggregate only.
CREATE FUNCTION app_llm_spend_usd(p_since timestamptz) RETURNS numeric
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT coalesce(sum(c.cost_usd), 0) FROM public.llm_calls c WHERE c.created_at >= p_since
$$;
"""

# Trigger functions: evidence immutability (AC-IP-2) and append-only tables. None is executable by any runtime role.
TRIGGERS_SQL = r"""
CREATE FUNCTION block_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: the table is append-only evidence', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

-- A version is inserted as a draft, without registration columns. While a draft, its keys never change and the
-- registration columns stay empty; registering it needs a linked problem, and the database sets registered_at to
-- now() whatever value is sent (the app never chooses its registration time). Once registered it is never deleted,
-- and an UPDATE may only fill content_hash, prev_version_hash and manifest_version while they are empty (updated_at
-- may move); only provenance_worker holds UPDATE on those columns. SECURITY DEFINER: reads proposal_problems whatever
-- the caller's visibility.
CREATE FUNCTION proposal_versions_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_allowed public.proposal_versions%ROWTYPE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'proposal_versions: a version is inserted as a draft and registered by UPDATE'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.registered_at IS NOT NULL OR NEW.content_hash IS NOT NULL OR NEW.prev_version_hash IS NOT NULL
           OR NEW.manifest_version IS NOT NULL THEN
            RAISE EXCEPTION 'proposal_versions: registered_at and the registration hashes are set at registration'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'registered' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'proposal_versions: a registered version is never deleted (AC-IP-2)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        v_allowed := OLD;
        IF OLD.content_hash IS NULL THEN
            v_allowed.content_hash := NEW.content_hash;
        END IF;
        IF OLD.prev_version_hash IS NULL THEN
            v_allowed.prev_version_hash := NEW.prev_version_hash;
        END IF;
        IF OLD.manifest_version IS NULL THEN
            v_allowed.manifest_version := NEW.manifest_version;
        END IF;
        v_allowed.updated_at := NEW.updated_at;
        IF NEW IS DISTINCT FROM v_allowed THEN
            RAISE EXCEPTION 'proposal_versions: a registered version is immutable (AC-IP-2)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    IF NEW.id <> OLD.id OR NEW.proposal_id <> OLD.proposal_id OR NEW.version_no <> OLD.version_no THEN
        RAISE EXCEPTION 'proposal_versions: id, proposal_id and version_no never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.content_hash IS NOT NULL OR NEW.prev_version_hash IS NOT NULL OR NEW.manifest_version IS NOT NULL THEN
        RAISE EXCEPTION 'proposal_versions: the registration hashes are filled after registration'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'registered' THEN
        IF NOT EXISTS (SELECT 1 FROM public.proposal_problems pp WHERE pp.proposal_version_id = NEW.id) THEN
            RAISE EXCEPTION 'proposal_versions: registering a version needs at least one linked problem'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.registered_at := now();
    ELSIF NEW.registered_at IS NOT NULL THEN
        RAISE EXCEPTION 'proposal_versions: registered_at is set at registration' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- Tier 2 follows its version: written only while the version is a draft (by its owner, for its proposal); once the
-- version is registered, never deleted and only the empty manifest pair may be filled (updated_at may move).
-- SECURITY DEFINER: the Tier-2 roles cannot read proposal_versions or proposals.
CREATE FUNCTION proposal_confidential_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_version uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.version_id ELSE NEW.version_id END;
    v_status public.version_status;
    v_proposal uuid;
    v_owner uuid;
    v_allowed public.proposal_confidential%ROWTYPE;
BEGIN
    SELECT v.status, v.proposal_id, p.owner_id INTO v_status, v_proposal, v_owner
      FROM public.proposal_versions v
      JOIN public.proposals p ON p.id = v.proposal_id
     WHERE v.id = v_version;
    IF TG_OP = 'INSERT' THEN
        IF v_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'proposal_confidential: Tier 2 is written only for a draft version'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.proposal_id <> v_proposal OR NEW.owner_id <> v_owner THEN
            RAISE EXCEPTION 'proposal_confidential: proposal_id and owner_id must be those of the version'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF v_status = 'registered' THEN
            RAISE EXCEPTION 'proposal_confidential: Tier 2 of a registered version is never deleted (AC-IP-2)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.version_id <> OLD.version_id OR NEW.proposal_id <> OLD.proposal_id OR NEW.owner_id <> OLD.owner_id THEN
        RAISE EXCEPTION 'proposal_confidential: version_id, proposal_id and owner_id never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_status = 'registered' THEN
        v_allowed := OLD;
        IF OLD.manifest_ciphertext IS NULL THEN
            v_allowed.manifest_ciphertext := NEW.manifest_ciphertext;
            v_allowed.manifest_nonce := NEW.manifest_nonce;
        END IF;
        v_allowed.updated_at := NEW.updated_at;
        IF NEW IS DISTINCT FROM v_allowed THEN
            RAISE EXCEPTION 'proposal_confidential: Tier 2 of a registered version is immutable (AC-IP-2)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Attachments of a registered version are evidence (their SHA-256s are in its manifest): never deleted, and an UPDATE
-- may change only av_status, rerendered and updated_at (the scanner and the PDF re-render). A draft's attachments
-- stay editable. SECURITY DEFINER: reads the version's status whatever the caller's visibility.
CREATE FUNCTION proposal_attachments_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_allowed public.proposal_attachments%ROWTYPE;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.proposal_versions v WHERE v.id = OLD.version_id AND v.status = 'registered'
    ) THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'proposal_attachments: an attachment of a registered version is never deleted (AC-IP-2)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    v_allowed := OLD;
    v_allowed.av_status := NEW.av_status;
    v_allowed.rerendered := NEW.rerendered;
    v_allowed.updated_at := NEW.updated_at;
    IF NEW IS DISTINCT FROM v_allowed THEN
        RAISE EXCEPTION 'proposal_attachments: an attachment of a registered version changes only its scan state'
            ' (AC-IP-2)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- Registration records: never deleted; an UPDATE may only fill empty signature, key, TSA, OpenTimestamps and evidence
-- columns and move status forward (hashed -> signed -> timestamped).
CREATE FUNCTION provenance_records_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_allowed public.provenance_records%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'provenance_records: evidence is never deleted (AC-IP-2)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    v_allowed := OLD;
    IF OLD.signature IS NULL THEN v_allowed.signature := NEW.signature; END IF;
    IF OLD.key_id IS NULL THEN v_allowed.key_id := NEW.key_id; END IF;
    IF OLD.tsa_token IS NULL THEN v_allowed.tsa_token := NEW.tsa_token; END IF;
    IF OLD.tsa_time IS NULL THEN v_allowed.tsa_time := NEW.tsa_time; END IF;
    IF OLD.tsa_serial IS NULL THEN v_allowed.tsa_serial := NEW.tsa_serial; END IF;
    IF OLD.tsa_url IS NULL THEN v_allowed.tsa_url := NEW.tsa_url; END IF;
    IF OLD.ots_proof IS NULL THEN v_allowed.ots_proof := NEW.ots_proof; END IF;
    IF OLD.evidence_s3_key IS NULL THEN v_allowed.evidence_s3_key := NEW.evidence_s3_key; END IF;
    IF NEW.status >= OLD.status THEN v_allowed.status := NEW.status; END IF;
    IF NEW IS DISTINCT FROM v_allowed THEN
        RAISE EXCEPTION 'provenance_records: only empty signature, TSA and evidence columns may be filled, and the'
            ' status only moves forward (AC-IP-2)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- current_version_id must be a registered version of the proposal and draft_version_id a draft one (the composite
-- foreign keys already keep both inside the proposal). Checked when either is set or changed, so register the version
-- first and point current_version_id at it afterwards. SECURITY DEFINER: reads proposal_versions whatever the
-- caller's visibility.
CREATE FUNCTION proposals_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.current_version_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.current_version_id IS DISTINCT FROM OLD.current_version_id)
       AND NOT EXISTS (
           SELECT 1 FROM public.proposal_versions v
            WHERE v.id = NEW.current_version_id AND v.proposal_id = NEW.id AND v.status = 'registered') THEN
        RAISE EXCEPTION 'proposals: current_version_id must be a registered version of the proposal'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.draft_version_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.draft_version_id IS DISTINCT FROM OLD.draft_version_id)
       AND NOT EXISTS (
           SELECT 1 FROM public.proposal_versions v
            WHERE v.id = NEW.draft_version_id AND v.proposal_id = NEW.id AND v.status = 'draft') THEN
        RAISE EXCEPTION 'proposals: draft_version_id must be a draft version of the proposal'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- A tag is open while closed_at IS NULL (uq_tags_open_developer_org: one open tag per developer and organisation).
-- Moving to withdrawn, expired or released closes it. A closed tag never reopens: closed_at keeps its value and the
-- status can only move to another closing status.
CREATE FUNCTION tags_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF OLD.closed_at IS NOT NULL AND (
        NEW.closed_at IS DISTINCT FROM OLD.closed_at
        OR (NEW.status IS DISTINCT FROM OLD.status AND NEW.status NOT IN ('withdrawn', 'expired', 'released'))
    ) THEN
        RAISE EXCEPTION 'tags: a closed tag never reopens' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IN ('withdrawn', 'expired', 'released') AND NEW.closed_at IS NULL THEN
        NEW.closed_at := now();
    END IF;
    RETURN NEW;
END;
$$;

-- A phone code expires 10 minutes after it is stored, by the database clock: whatever expiry the writer sends is
-- replaced (D1 codes are never valid longer, however the application's clock runs).
CREATE FUNCTION phone_verifications_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    NEW.expires_at := now() + interval '10 minutes';
    RETURN NEW;
END;
$$;

-- One claim per claimant and organisation per 24 hours, whatever became of the earlier one: withdrawing and claiming
-- again cannot reset the OTP attempt and reissue limits. (One open claim per claimant and organisation is also a
-- partial unique index.) SECURITY DEFINER: sees the claimant's earlier claims whatever the caller's visibility.
CREATE FUNCTION org_claims_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.org_claims c
         WHERE c.org_id = NEW.org_id AND c.claimant_user_id = NEW.claimant_user_id
           AND c.created_at > now() - interval '24 hours'
    ) THEN
        RAISE EXCEPTION 'org_claims: one claim per claimant and organisation per 24 hours'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION proposals_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION tags_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION org_claims_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION phone_verifications_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION block_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION proposal_versions_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION proposal_confidential_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION provenance_records_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION proposal_attachments_guard() FROM PUBLIC;

CREATE TRIGGER proposal_versions_guard
    BEFORE INSERT OR UPDATE OR DELETE ON proposal_versions
    FOR EACH ROW EXECUTE FUNCTION proposal_versions_guard();
CREATE TRIGGER proposal_confidential_guard
    BEFORE INSERT OR UPDATE OR DELETE ON proposal_confidential
    FOR EACH ROW EXECUTE FUNCTION proposal_confidential_guard();
CREATE TRIGGER provenance_records_guard
    BEFORE UPDATE OR DELETE ON provenance_records
    FOR EACH ROW EXECUTE FUNCTION provenance_records_guard();
CREATE TRIGGER proposal_attachments_guard
    BEFORE UPDATE OR DELETE ON proposal_attachments
    FOR EACH ROW EXECUTE FUNCTION proposal_attachments_guard();
CREATE TRIGGER proposals_guard
    BEFORE INSERT OR UPDATE ON proposals
    FOR EACH ROW EXECUTE FUNCTION proposals_guard();
CREATE TRIGGER tags_guard
    BEFORE UPDATE ON tags
    FOR EACH ROW EXECUTE FUNCTION tags_guard();
CREATE TRIGGER org_claims_guard
    BEFORE INSERT ON org_claims
    FOR EACH ROW EXECUTE FUNCTION org_claims_guard();
CREATE TRIGGER phone_verifications_guard
    BEFORE INSERT ON phone_verifications
    FOR EACH ROW EXECUTE FUNCTION phone_verifications_guard();
"""

APPEND_ONLY_TABLES = ("attestations", "nda_acceptances", "legal_acceptances", "chain_anchors", "transparency_roots")
NO_TRUNCATE_TABLES = (*APPEND_ONLY_TABLES, "proposal_versions", "proposal_confidential", "provenance_records")

# EXECUTE grants (every function above has EXECUTE revoked from PUBLIC first). The Tier-2 roles need the helpers their
# policies call; app_org_id() and app_is_member() are only called inside definer functions for them.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_is_staff(staff_role[])": ("bridge_app", "tier2_moderation"),
    "app_current_legal_template(legal_template_kind)": ("bridge_app",),
    "app_owns_version(uuid)": ("provenance_worker",),
    "app_subject_digest(uuid, bytea)": ("bridge_app", "provenance_worker"),
    "app_tier2_granted(uuid, uuid)": ("bridge_app", "tier2_reader"),
    "app_held_tag_count(uuid)": ("bridge_app",),
    "app_confirm_phone_otp(uuid, bytea)": ("bridge_app",),
    "app_decide_kyc(uuid, boolean, text, text, text, text, boolean)": ("bridge_app",),
    "app_kyc_purge_due()": ("bridge_app",),
    "app_mark_kyc_images_purged(uuid)": ("bridge_app",),
    "app_moderate_proposal(uuid, moderation_state)": ("bridge_app",),
    "app_moderate_problem(uuid, moderation_state, problem_status)": ("bridge_app",),
    "app_hold_proposal(uuid)": ("bridge_app",),
    "app_hold_problem(uuid)": ("bridge_app",),
    "app_confirm_claim_otp(uuid, bytea)": ("bridge_app",),
    "app_approve_claim_e1(uuid)": ("bridge_app",),
    "app_decide_claim(uuid, boolean, text)": ("bridge_app",),
    "app_delist_org(uuid)": ("bridge_app",),
    "app_opt_out_org_invitations(uuid)": ("bridge_app",),
    "app_llm_spend_usd(timestamp with time zone)": ("bridge_app",),
    "app_llm_call_inputs(uuid)": ("bridge_app",),
    "app_add_niche(text, text, text, text)": ("bridge_app",),
    "app_reissue_claim_otp(uuid, bytea, timestamp with time zone)": ("bridge_app",),
    "app_close_tag(uuid)": ("bridge_app",),
    "app_audit_chain_heads()": ("provenance_worker",),
}
# Revision 0001 helpers the Tier-2 roles' policies call (revoked again on downgrade).
FUNCTION_GRANTS_0001: dict[str, tuple[str, ...]] = {"app_user_id()": TIER2_ROLES}
TRIGGER_FUNCTIONS = (
    "block_mutation()",
    "proposal_versions_guard()",
    "proposal_confidential_guard()",
    "provenance_records_guard()",
    "proposal_attachments_guard()",
    "proposals_guard()",
    "tags_guard()",
    "org_claims_guard()",
    "phone_verifications_guard()",
)


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _grant_sql() -> str:
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    grants += [f"GRANT {privileges} ON TABLE {t} TO bridge_app;" for t, privileges in APP_GRANTS_0001_TABLES.items()]
    # REVOKE of a table privilege also revokes it on every column; the column grant follows.
    grants += [
        "REVOKE SELECT ON TABLE users FROM bridge_app;",
        f"GRANT SELECT ({USERS_READABLE_COLUMNS}) ON TABLE users TO bridge_app;",
    ]
    grants += [
        f"GRANT {privileges} ON TABLE {table} TO {role};"
        for role, tables in ROLE_GRANTS.items()
        for table, privileges in tables.items()
    ]
    for signature, roles in (FUNCTION_GRANTS | FUNCTION_GRANTS_0001).items():
        if signature in FUNCTION_GRANTS:
            grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _run_sql(PREFLIGHT_SQL)
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)
    _alter_phase1_tables()
    _create_tables()
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(
        "\n".join(
            [
                *(
                    f"CREATE TRIGGER {t}_no_update_delete BEFORE UPDATE OR DELETE ON {t}"
                    " FOR EACH ROW EXECUTE FUNCTION block_mutation();"
                    for t in APPEND_ONLY_TABLES
                ),
                *(
                    f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t}"
                    " FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();"
                    for t in NO_TRUNCATE_TABLES
                ),
            ]
        )
    )
    _run_sql(_grant_sql())


def downgrade() -> None:
    # Every policy of this revision first: policies depend on the tables their subqueries read (and the listed-org
    # policies on the 0001 columns dropped below), so no table could be dropped while they exist.
    _run_sql("\n".join(f"DROP POLICY {policy.name} ON {policy.table};" for policy in POLICIES))
    op.drop_constraint("fk_proposals_current_version", "proposals", type_="foreignkey")
    op.drop_constraint("fk_proposals_draft_version", "proposals", type_="foreignkey")
    # Dropping a table drops its policies, triggers, indexes and grants. Referencing tables before referenced ones.
    for table in (
        "brief_invitations",
        "problem_briefs",
        "problem_sources",
        "proposal_problems",
        "proposal_confidential_embeddings",
        "proposal_confidential",
        "proposal_attachments",
        "document_views",
        "nda_acceptances",
        "legal_acceptances",
        "nda_templates",
        "legal_templates",
        "engagements",
        "attestations",
        "provenance_records",
        "transparency_roots",
        "chain_anchors",
        "provenance_keys",
        "tags",
        "disclosure_grants",
        "proposal_lsh_bands",
        "originality_checks",
        "proposal_versions",
        "proposals",
        "problems",
        "signal_events",
        "moderation_cases",
        "org_claims",
        "directory_invitations",
        "phone_verifications",
        "kyc_reviews",
        "llm_calls",
    ):
        op.drop_table(table)
    _run_sql(
        "\n".join(
            [
                *(f"DROP FUNCTION {signature};" for signature in (*FUNCTION_GRANTS, *TRIGGER_FUNCTIONS)),
                *(
                    f"REVOKE EXECUTE ON FUNCTION {signature} FROM {', '.join(roles)};"
                    for signature, roles in FUNCTION_GRANTS_0001.items()
                ),
            ]
        )
    )
    op.drop_constraint(op.f("fk_organizations_county_code_regions"), "organizations", type_="foreignkey")
    for column in (
        "suspended_at",
        "reverify_due_on",
        "e2_verified_at",
        "invitations_opted_out_at",
        "delisted_at",
        "county_code",
        "source_retrieved_on",
        "source_url",
        "official_domains",
    ):
        op.drop_column("organizations", column)
    op.drop_column("users", "subject_salt")
    _run_sql("REVOKE SELECT ON TABLE users FROM bridge_app; GRANT SELECT ON TABLE users TO bridge_app;")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)


def _alter_phase1_tables() -> None:
    op.add_column(
        "organizations",
        sa.Column("official_domains", postgresql.ARRAY(postgresql.CITEXT()), server_default="{}", nullable=False),
    )
    op.add_column("organizations", sa.Column("source_url", sa.String(length=500), nullable=True))
    op.add_column("organizations", sa.Column("source_retrieved_on", sa.Date(), nullable=True))
    op.add_column("organizations", sa.Column("county_code", sa.String(length=8), nullable=True))
    op.add_column("organizations", sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("invitations_opted_out_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("e2_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("reverify_due_on", sa.Date(), nullable=True))
    op.add_column("organizations", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_organizations_county_code_regions"), "organizations", "regions", ["county_code"], ["code"]
    )
    # A volatile default: every existing user gets their own random salt.
    op.add_column(
        "users",
        sa.Column("subject_salt", sa.LargeBinary(), server_default=sa.text("gen_random_bytes(32)"), nullable=False),
    )


def _create_tables() -> None:
    op.create_table(
        "chain_anchors",
        sa.Column("chain_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_hash", sa.LargeBinary(), nullable=False),
        sa.Column("tsa_token", sa.LargeBinary(), nullable=False),
        sa.Column("tsa_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tsa_serial", sa.String(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("octet_length(event_hash) = 32", name=op.f("ck_chain_anchors_event_hash_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chain_anchors")),
        sa.UniqueConstraint("chain_id", "seq", name=op.f("uq_chain_anchors_chain_id_seq")),
    )
    op.create_table(
        "legal_templates",
        sa.Column("kind", _enum("legal_template_kind"), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_placeholder", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sha256 = sha256(convert_to(body, 'UTF8'))", name=op.f("ck_legal_templates_sha256_of_body")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_templates")),
        sa.UniqueConstraint("id", "sha256", name=op.f("uq_legal_templates_id_sha256")),
        sa.UniqueConstraint("kind", "version", name=op.f("uq_legal_templates_kind_version")),
    )
    op.create_table(
        "provenance_keys",
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=16), server_default="ed25519", nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("algorithm = 'ed25519'", name=op.f("ck_provenance_keys_algorithm")),
        sa.CheckConstraint("octet_length(public_key) = 32", name=op.f("ck_provenance_keys_public_key_length")),
        sa.PrimaryKeyConstraint("key_id", name=op.f("pk_provenance_keys")),
    )
    op.create_table(
        "signal_events",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("actor_hash", sa.LargeBinary(), nullable=True),
        sa.Column("org_hash", sa.LargeBinary(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_events")),
    )
    op.create_index("ix_signal_events_kind_ts", "signal_events", ["kind", "ts"], unique=False)
    op.create_table(
        "kyc_reviews",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("kyc_status"), server_default="submitted", nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("verified_legal_name", sa.String(length=200), nullable=True),
        sa.Column("id_type", sa.String(length=24), nullable=True),
        sa.Column("id_last4", sa.String(length=4), nullable=True),
        sa.Column("is_adult", sa.Boolean(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("images_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id_last4 IS NULL OR id_last4 ~ '^[0-9A-Za-z]{4}$'", name=op.f("ck_kyc_reviews_id_last4")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_kyc_reviews_decided_by_users")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_kyc_reviews_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_reviews")),
    )
    op.create_index(op.f("ix_kyc_reviews_user_id"), "kyc_reviews", ["user_id"], unique=False)
    op.create_table(
        "moderation_cases",
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("reasons", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("source", _enum("moderation_source"), nullable=False),
        sa.Column("status", _enum("moderation_case_status"), server_default="open", nullable=False),
        sa.Column("classifier", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reporter_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], name=op.f("fk_moderation_cases_assigned_to_users")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_moderation_cases_decided_by_users")),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], name=op.f("fk_moderation_cases_reporter_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moderation_cases")),
    )
    op.create_index("ix_moderation_cases_status_created_at", "moderation_cases", ["status", "created_at"], unique=False)
    op.create_index("ix_moderation_cases_subject", "moderation_cases", ["subject_type", "subject_id"], unique=False)
    op.create_table(
        "nda_templates",
        sa.Column("kind", _enum("nda_kind"), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("legal_template_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["legal_template_id", "sha256"],
            ["legal_templates.id", "legal_templates.sha256"],
            name="fk_nda_templates_legal_template",
            onupdate="CASCADE",  # the NDA's hash follows its body until an acceptance pins it (NO ACTION)
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nda_templates")),
        sa.UniqueConstraint("id", "sha256", name=op.f("uq_nda_templates_id_sha256")),
        sa.UniqueConstraint("kind", "version", name=op.f("uq_nda_templates_kind_version")),
    )
    op.create_table(
        "originality_checks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("band", _enum("originality_band"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_originality_checks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_originality_checks")),
    )
    op.create_index(
        "ix_originality_checks_user_id_created_at", "originality_checks", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "phone_verifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("otp_hash", sa.LargeBinary(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() + '00:10:00'::interval)"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("phone_e164 ~ '^\\+[1-9][0-9]{6,14}$'", name=op.f("ck_phone_verifications_phone_e164")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_phone_verifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_verifications")),
    )
    op.create_index(op.f("ix_phone_verifications_user_id"), "phone_verifications", ["user_id"], unique=False)
    op.create_table(
        "proposals",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("proposal_status"), server_default="draft", nullable=False),
        sa.Column("moderation_state", _enum("moderation_state"), server_default="clear", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("draft_version_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("niche_id", sa.Uuid(), nullable=True),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("maturity", _enum("proposal_maturity"), nullable=True),
        sa.Column("ask", _enum("proposal_ask"), nullable=True),
        sa.Column("problem_statement", sa.Text(), nullable=True),
        sa.Column("impact_claims", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                SEARCH_TSV,
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("teaser_embedding", Vector(1024), nullable=True),
        sa.Column("embed_model", sa.String(length=80), nullable=True),
        sa.Column("embed_version", sa.String(length=40), nullable=True),
        sa.Column("tier2_policy", _enum("tier2_policy"), server_default="auto_tagged", nullable=False),
        sa.Column("raw_download_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status = 'draft' OR current_version_id IS NOT NULL", name=op.f("ck_proposals_listed_has_version")
        ),
        sa.ForeignKeyConstraint(["county_code"], ["regions.code"], name=op.f("fk_proposals_county_code_regions")),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_proposals_niche_id_niches")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_proposals_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
    )
    op.create_index(op.f("ix_proposals_niche_id"), "proposals", ["niche_id"], unique=False)
    op.create_index(op.f("ix_proposals_owner_id"), "proposals", ["owner_id"], unique=False)
    op.create_index("ix_proposals_search_tsv", "proposals", ["search_tsv"], unique=False, postgresql_using="gin")
    op.create_index(
        "ix_proposals_teaser_embedding",
        "proposals",
        ["teaser_embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"teaser_embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "transparency_roots",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("merkle_root", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("octet_length(merkle_root) = 32", name=op.f("ck_transparency_roots_merkle_root_length")),
        sa.ForeignKeyConstraint(
            ["key_id"], ["provenance_keys.key_id"], name=op.f("fk_transparency_roots_key_id_provenance_keys")
        ),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_transparency_roots")),
    )
    op.create_table(
        "directory_invitations",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("to_address", postgresql.CITEXT(), nullable=False),
        sa.Column("status", _enum("directory_invitation_status"), server_default="proposed", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("proposed_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name=op.f("fk_directory_invitations_approved_by_users")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_directory_invitations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"], name=op.f("fk_directory_invitations_proposed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_invitations")),
    )
    op.create_index(op.f("ix_directory_invitations_org_id"), "directory_invitations", ["org_id"], unique=False)
    op.create_table(
        "disclosure_grants",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("status", _enum("grant_status"), nullable=False),
        sa.Column("source", _enum("grant_source"), nullable=False),
        sa.Column("counts_as_unlock", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("billing_month", sa.Date(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("tier IN (2, 3)", name=op.f("ck_disclosure_grants_tier")),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name=op.f("fk_disclosure_grants_granted_by_users")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_disclosure_grants_org_id_organizations")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_disclosure_grants_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposals.id"], name=op.f("fk_disclosure_grants_proposal_id_proposals")
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_disclosure_grants_requested_by_users")),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name=op.f("fk_disclosure_grants_revoked_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disclosure_grants")),
    )
    op.create_index(op.f("ix_disclosure_grants_org_id"), "disclosure_grants", ["org_id"], unique=False)
    op.create_index(op.f("ix_disclosure_grants_owner_id"), "disclosure_grants", ["owner_id"], unique=False)
    op.create_index(op.f("ix_disclosure_grants_proposal_id"), "disclosure_grants", ["proposal_id"], unique=False)
    op.create_index(
        "uq_disclosure_grants_live",
        "disclosure_grants",
        ["proposal_id", "org_id", "tier"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'active')"),
    )
    op.create_table(
        "legal_acceptances",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("legal_template_id", sa.Uuid(), nullable=False),
        sa.Column("template_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["legal_template_id", "template_sha256"],
            ["legal_templates.id", "legal_templates.sha256"],
            name="fk_legal_acceptances_template",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_legal_acceptances_org_id_organizations")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_legal_acceptances_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_acceptances")),
    )
    op.create_index(op.f("ix_legal_acceptances_org_id"), "legal_acceptances", ["org_id"], unique=False)
    op.create_index(op.f("ix_legal_acceptances_user_id"), "legal_acceptances", ["user_id"], unique=False)
    op.create_table(
        "llm_calls",
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stop_reason", sa.String(length=40), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_llm_calls_org_id_organizations")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_llm_calls_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], unique=False)
    op.create_index("ix_llm_calls_org_id_created_at", "llm_calls", ["org_id", "created_at"], unique=False)
    op.create_index("ix_llm_calls_user_id_created_at", "llm_calls", ["user_id", "created_at"], unique=False)
    op.create_table(
        "nda_acceptances",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("nda_template_id", sa.Uuid(), nullable=False),
        sa.Column("template_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("logging_notice_version", sa.String(length=32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["nda_template_id", "template_sha256"],
            ["nda_templates.id", "nda_templates.sha256"],
            name="fk_nda_acceptances_template",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_nda_acceptances_org_id_organizations")),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposals.id"], name=op.f("fk_nda_acceptances_proposal_id_proposals")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_nda_acceptances_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nda_acceptances")),
    )
    op.create_index(op.f("ix_nda_acceptances_org_id"), "nda_acceptances", ["org_id"], unique=False)
    op.create_index(op.f("ix_nda_acceptances_proposal_id"), "nda_acceptances", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_nda_acceptances_user_id"), "nda_acceptances", ["user_id"], unique=False)
    op.create_table(
        "org_claims",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("claimant_user_id", sa.Uuid(), nullable=False),
        sa.Column("domain", postgresql.CITEXT(), nullable=False),
        sa.Column("email_address", postgresql.CITEXT(), nullable=False),
        sa.Column("level", _enum("claim_level"), nullable=False),
        sa.Column("status", _enum("claim_status"), nullable=False),
        sa.Column("otp_hash", sa.LargeBinary(), nullable=True),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("otp_reissues", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("otp_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dns_token", sa.String(length=64), nullable=True),
        sa.Column("dns_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_no", sa.String(length=64), nullable=True),
        sa.Column("cr12_date", sa.Date(), nullable=True),
        sa.Column("kra_pin", sa.String(length=16), nullable=True),
        sa.Column("sector_register", sa.String(length=80), nullable=True),
        sa.Column("public_entity_requested", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("document_keys", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["claimant_user_id"], ["users.id"], name=op.f("fk_org_claims_claimant_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_org_claims_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_org_claims_reviewed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_claims")),
    )
    op.create_index(op.f("ix_org_claims_claimant_user_id"), "org_claims", ["claimant_user_id"], unique=False)
    op.create_index(op.f("ix_org_claims_org_id"), "org_claims", ["org_id"], unique=False)
    op.create_index(
        "uq_org_claims_open_claimant_org",
        "org_claims",
        ["org_id", "claimant_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('otp_sent', 'dns_pending', 'pending_review', 'disputed')"),
    )
    op.create_table(
        "problems",
        sa.Column("source", _enum("problem_source"), nullable=False),
        sa.Column("niche_id", sa.Uuid(), nullable=True),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("title", sa.String(length=90), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("affected_group", sa.String(length=200), nullable=True),
        sa.Column("status", _enum("problem_status"), server_default="pending_review", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("ai_generated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("cluster_id", sa.Uuid(), nullable=True),
        sa.Column("moderator_id", sa.Uuid(), nullable=True),
        sa.Column("moderation_state", _enum("moderation_state"), server_default="clear", nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embed_model", sa.String(length=80), nullable=True),
        sa.Column("embed_version", sa.String(length=40), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["county_code"], ["regions.code"], name=op.f("fk_problems_county_code_regions")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_problems_created_by_users")),
        sa.ForeignKeyConstraint(["moderator_id"], ["users.id"], name=op.f("fk_problems_moderator_id_users")),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_problems_niche_id_niches")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_problems_org_id_organizations")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_problems")),
        sa.UniqueConstraint("id", "org_id", name=op.f("uq_problems_id_org_id")),
    )
    op.create_index(op.f("ix_problems_created_by"), "problems", ["created_by"], unique=False)
    op.create_index(op.f("ix_problems_niche_id"), "problems", ["niche_id"], unique=False)
    op.create_index(op.f("ix_problems_org_id"), "problems", ["org_id"], unique=False)
    op.create_table(
        "proposal_lsh_bands",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("band", sa.SmallInteger(), nullable=False),
        sa.Column("bucket", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_proposal_lsh_bands_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("proposal_id", "band", name=op.f("pk_proposal_lsh_bands")),
    )
    op.create_index("ix_proposal_lsh_bands_band_bucket", "proposal_lsh_bands", ["band", "bucket"], unique=False)
    op.create_table(
        "proposal_versions",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", _enum("version_status"), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("niche_id", sa.Uuid(), nullable=True),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("maturity", _enum("proposal_maturity"), nullable=True),
        sa.Column("ask", _enum("proposal_ask"), nullable=True),
        sa.Column("problem_statement", sa.Text(), nullable=True),
        sa.Column("impact_claims", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("owner_handle", postgresql.CITEXT(), nullable=True),
        sa.Column("prev_version_hash", sa.LargeBinary(), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=True),
        sa.Column("cert_id", sa.String(length=24), nullable=True),
        sa.Column("manifest_version", sa.String(length=16), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            REGISTERED_IS_COMPLETE,
            name=op.f("ck_proposal_versions_registered_is_complete"),
        ),
        sa.CheckConstraint(
            "content_hash IS NULL OR octet_length(content_hash) = 32",
            name=op.f("ck_proposal_versions_content_hash_length"),
        ),
        sa.CheckConstraint(
            "prev_version_hash IS NULL OR octet_length(prev_version_hash) = 32",
            name=op.f("ck_proposal_versions_prev_version_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["county_code"], ["regions.code"], name=op.f("fk_proposal_versions_county_code_regions")
        ),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_proposal_versions_niche_id_niches")),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_proposal_versions_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_versions")),
        sa.UniqueConstraint("cert_id", name=op.f("uq_proposal_versions_cert_id")),
        sa.UniqueConstraint("proposal_id", "id", name=op.f("uq_proposal_versions_proposal_id_id")),
        sa.UniqueConstraint("proposal_id", "version_no", name=op.f("uq_proposal_versions_proposal_id_version_no")),
    )
    op.create_table(
        "tags",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("tag_status"), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status NOT IN ('withdrawn', 'expired', 'released') OR closed_at IS NOT NULL",
            name=op.f("ck_tags_closing_statuses_are_closed"),
        ),
        sa.ForeignKeyConstraint(["developer_id"], ["users.id"], name=op.f("fk_tags_developer_id_users")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_tags_org_id_organizations")),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_tags_proposal_id_proposals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
    )
    op.create_index(op.f("ix_tags_developer_id"), "tags", ["developer_id"], unique=False)
    op.create_index(op.f("ix_tags_org_id"), "tags", ["org_id"], unique=False)
    op.create_index(op.f("ix_tags_proposal_id"), "tags", ["proposal_id"], unique=False)
    op.create_index(
        "uq_tags_open_developer_org",
        "tags",
        ["developer_id", "org_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_table(
        "attestations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("created_it", sa.Boolean(), nullable=False),
        sa.Column("not_owned_by_employer_or_client", sa.Boolean(), nullable=False),
        sa.Column("no_third_party_confidential", sa.Boolean(), nullable=False),
        sa.Column("text_version", sa.String(length=32), nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("octet_length(text_sha256) = 32", name=op.f("ck_attestations_text_sha256_length")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_attestations_user_id_users")),
        sa.ForeignKeyConstraint(
            ["version_id"], ["proposal_versions.id"], name=op.f("fk_attestations_version_id_proposal_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attestations")),
    )
    op.create_index(op.f("ix_attestations_user_id"), "attestations", ["user_id"], unique=False)
    op.create_index(op.f("ix_attestations_version_id"), "attestations", ["version_id"], unique=False)
    op.create_table(
        "document_views",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("viewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("nda_acceptance_id", sa.Uuid(), nullable=True),
        sa.Column("nda_template_version", sa.String(length=32), nullable=True),
        sa.Column("render_kind", _enum("render_kind"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("duration_bucket", _enum("view_duration"), nullable=True),
        sa.Column("fingerprint_seed", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["nda_acceptance_id"],
            ["nda_acceptances.id"],
            name=op.f("fk_document_views_nda_acceptance_id_nda_acceptances"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_document_views_org_id_organizations")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_document_views_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_document_views_version",
        ),
        sa.ForeignKeyConstraint(["viewer_user_id"], ["users.id"], name=op.f("fk_document_views_viewer_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_views")),
    )
    op.create_index(op.f("ix_document_views_org_id"), "document_views", ["org_id"], unique=False)
    op.create_index(op.f("ix_document_views_owner_id"), "document_views", ["owner_id"], unique=False)
    op.create_index(op.f("ix_document_views_proposal_id"), "document_views", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_document_views_viewer_user_id"), "document_views", ["viewer_user_id"], unique=False)
    op.create_table(
        "engagements",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("origin", _enum("engagement_origin"), nullable=False),
        sa.Column("state", _enum("engagement_state"), nullable=False),
        sa.Column("end_reason", _enum("engagement_end_reason"), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            END_REASON_MATCHES_STATE,
            name=op.f("ck_engagements_end_reason_matches_state"),
        ),
        sa.ForeignKeyConstraint(["developer_id"], ["users.id"], name=op.f("fk_engagements_developer_id_users")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_engagements_org_id_organizations")),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_engagements_version",
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_engagements_proposal_id_proposals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagements")),
        sa.UniqueConstraint("proposal_id", "org_id", name=op.f("uq_engagements_proposal_id_org_id")),
    )
    op.create_index(op.f("ix_engagements_developer_id"), "engagements", ["developer_id"], unique=False)
    op.create_index(op.f("ix_engagements_org_id"), "engagements", ["org_id"], unique=False)
    op.create_table(
        "problem_briefs",
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", _enum("brief_visibility"), server_default="public", nullable=False),
        sa.Column("budget_band", sa.String(length=32), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", _enum("brief_status"), server_default="draft", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_problem_briefs_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["problem_id", "org_id"],
            ["problems.id", "problems.org_id"],
            name="fk_problem_briefs_problem",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("problem_id", name=op.f("pk_problem_briefs")),
        sa.UniqueConstraint("problem_id", "org_id", name=op.f("uq_problem_briefs_problem_id_org_id")),
    )
    op.create_index(op.f("ix_problem_briefs_org_id"), "problem_briefs", ["org_id"], unique=False)
    op.create_table(
        "problem_sources",
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name=op.f("fk_problem_sources_problem_id_problems"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_problem_sources")),
    )
    op.create_index(op.f("ix_problem_sources_problem_id"), "problem_sources", ["problem_id"], unique=False)
    op.create_table(
        "proposal_attachments",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("av_status", _enum("av_status"), server_default="pending_upload", nullable=False),
        sa.Column("rerendered", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "sha256 IS NULL OR octet_length(sha256) = 32", name=op.f("ck_proposal_attachments_sha256_length")
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 20971520", name=op.f("ck_proposal_attachments_size_limit")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_proposal_attachments_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_proposal_attachments_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_attachments")),
    )
    op.create_index(op.f("ix_proposal_attachments_owner_id"), "proposal_attachments", ["owner_id"], unique=False)
    op.create_index(op.f("ix_proposal_attachments_proposal_id"), "proposal_attachments", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_proposal_attachments_version_id"), "proposal_attachments", ["version_id"], unique=False)
    op.create_table(
        "proposal_confidential",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("kms_key_id", sa.String(length=200), nullable=False),
        sa.Column("manifest_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("manifest_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(manifest_ciphertext IS NULL) = (manifest_nonce IS NULL)",
            name=op.f("ck_proposal_confidential_manifest_pair"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_proposal_confidential_owner_id_users")),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_proposal_confidential_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_proposal_confidential")),
    )
    op.create_index(op.f("ix_proposal_confidential_owner_id"), "proposal_confidential", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_proposal_confidential_proposal_id"), "proposal_confidential", ["proposal_id"], unique=False
    )
    op.create_table(
        "proposal_problems",
        sa.Column("proposal_version_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], name=op.f("fk_proposal_problems_problem_id_problems")),
        sa.ForeignKeyConstraint(
            ["proposal_version_id"],
            ["proposal_versions.id"],
            name=op.f("fk_proposal_problems_proposal_version_id_proposal_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("proposal_version_id", "problem_id", name=op.f("pk_proposal_problems")),
    )
    op.create_index(op.f("ix_proposal_problems_problem_id"), "proposal_problems", ["problem_id"], unique=False)
    op.create_table(
        "provenance_records",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("cert_id", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=True),
        sa.Column("key_id", sa.String(length=64), nullable=True),
        sa.Column("status", _enum("provenance_status"), server_default="hashed", nullable=False),
        sa.Column("tsa_token", sa.LargeBinary(), nullable=True),
        sa.Column("tsa_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tsa_serial", sa.String(length=128), nullable=True),
        sa.Column("tsa_url", sa.String(length=500), nullable=True),
        sa.Column("ots_proof", sa.LargeBinary(), nullable=True),
        sa.Column("evidence_s3_key", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status <> 'timestamped' OR (tsa_token IS NOT NULL AND tsa_time IS NOT NULL)",
            name=op.f("ck_provenance_records_tsa"),
        ),
        sa.CheckConstraint(
            "status = 'hashed' OR (signature IS NOT NULL AND key_id IS NOT NULL)",
            name=op.f("ck_provenance_records_signed_has_key"),
        ),
        sa.CheckConstraint("octet_length(content_hash) = 32", name=op.f("ck_provenance_records_content_hash_length")),
        sa.ForeignKeyConstraint(
            ["key_id"], ["provenance_keys.key_id"], name=op.f("fk_provenance_records_key_id_provenance_keys")
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["proposal_versions.id"], name=op.f("fk_provenance_records_version_id_proposal_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provenance_records")),
        sa.UniqueConstraint("cert_id", name=op.f("uq_provenance_records_cert_id")),
        sa.UniqueConstraint("version_id", name=op.f("uq_provenance_records_version_id")),
    )
    op.create_table(
        "brief_invitations",
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["brief_id", "org_id"],
            ["problem_briefs.problem_id", "problem_briefs.org_id"],
            name="fk_brief_invitations_brief",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_brief_invitations_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brief_invitations")),
        sa.UniqueConstraint("brief_id", "user_id", name=op.f("uq_brief_invitations_brief_id_user_id")),
    )
    op.create_index(op.f("ix_brief_invitations_org_id"), "brief_invitations", ["org_id"], unique=False)
    op.create_index(op.f("ix_brief_invitations_user_id"), "brief_invitations", ["user_id"], unique=False)
    op.create_table(
        "proposal_confidential_embeddings",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("embed_model", sa.String(length=80), nullable=False),
        sa.Column("embed_version", sa.String(length=40), nullable=False),
        sa.Column("full_embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["proposal_confidential.version_id"],
            name=op.f("fk_proposal_confidential_embeddings_version_id_proposal_confidential"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "version_id", "embed_model", "embed_version", name=op.f("pk_proposal_confidential_embeddings")
        ),
    )
    op.create_index(
        "ix_proposal_confidential_embeddings_full_embedding",
        "proposal_confidential_embeddings",
        ["full_embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"full_embedding": "vector_cosine_ops"},
    )
    # The circular foreign keys of proposals (each points at a version of the same proposal).
    op.create_foreign_key(
        "fk_proposals_current_version",
        "proposals",
        "proposal_versions",
        ["id", "current_version_id"],
        ["proposal_id", "id"],
    )
    op.create_foreign_key(
        "fk_proposals_draft_version",
        "proposals",
        "proposal_versions",
        ["id", "draft_version_id"],
        ["proposal_id", "id"],
    )
