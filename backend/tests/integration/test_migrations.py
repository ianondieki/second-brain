"""Revisions 0001 to 0009 (REQ-TEN-01, REQ-AUD-01, REQ-CON-01, REQ-REPO-01, REQ-PROV-01, REQ-ENG-01, REQ-ENG-02,
REQ-LLM-01, REQ-SCOUT-01, REQ-RES-01, REQ-TREND-01, REQ-BIL-08, REQ-ENG-10, REQ-NOT-03, REQ-PROP-03, REQ-ENG-11,
REQ-REPO-02, REQ-PERS-03, REQ-DEV-01; docs/spec/08 Migrations and Tenancy; AC-IP-2).

Migration round trip and drift (each of 0009, 0008, 0007, 0006, 0005, 0004, 0003 and 0002 leaves the revision before it
exactly as it found it), table classification, RLS coverage generated from the ORM metadata, the grant matrix of every
role, role attributes, the helper and SECURITY DEFINER functions, the append-only hash-chained audit log, the evidence
triggers of schema v2, the tracker triggers of schema v3, the schema v4 triggers and column grants, the schema v5 notes
triggers, policies and in-app column grant, the tags policies revision 0007 leaves as they were, the schema v6
(revision 0008) and v7 (revision 0009) policies, triggers and column grants, the listed-organisations policy and the
Procrastinate schema.
The tracker's behaviour (chain, projection, parties, payments, clock) is tested in ``integration/engagements/``;
schema v4's in ``integration/matching/``, ``integration/problems/`` and ``integration/billing/``; schema v5's (the
notes' writers and readers, marking read) in ``test_rls.py``; revision 0007's ``app_close_tag(tag, status)`` in
``test_privileges.py``; schema v6's (the thread, its stage gate and report, the shortlist, saved searches and their
job) in ``integration/engagements/test_messages_schema.py``, ``integration/engagements/test_messages_race.py``,
``integration/proposals/test_shortlist_schema.py`` and ``integration/profiles/test_saved_searches_schema.py``; schema
v7's (the quiz: its readers, the attempt and flag rules, rescoring, the board, the job's functions) in
``integration/quiz/test_quiz_schema.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import bridge.models.all  # noqa: F401  # registers every table
from bridge.ids import uuid7
from bridge.models import Base, Tenancy
from bridge.models.base import RLS_TENANCIES
from tests.integration import world as w
from tests.integration.conftest import BACKEND, create_database, drop_database, role_engine, run_alembic
from tests.integration.engagements import tracker

TABLES = Base.metadata.tables
TIER2_ROLES = ("tier2_reader", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "dsr_exporter")
RUNTIME_ROLES = ("bridge_app", "aggregate_worker", "audit_reader", *TIER2_ROLES)
ROLES = ("bridge_owner", *RUNTIME_ROLES)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

# The grant matrix of bridge_app (task cards T1.4 and T2.1, and review). Every other privilege on every ORM table
# must be absent. UPDATE is column-scoped where some columns are never the app's to change (APP_COLUMN_UPDATES).
S, I, U, D = "SELECT", "INSERT", "UPDATE", "DELETE"  # noqa: E741
APP_COLUMN_UPDATES: dict[str, set[str]] = {
    "users": {
        "email_verified_at",
        "password_hash",
        "display_name",
        "locale",
        "totp_secret_enc",
        "totp_pending_enc",
        "totp_enabled_at",
        "totp_last_counter",
        "totp_recovery_hashes",
        "updated_at",
    },
    "organizations": {
        "legal_name",
        "website",
        "regions",
        "registration_no",
        "sector_id",
        "country",
        "updated_at",
        "county_code",  # revision 0002
    },
    "developer_profiles": {"headline", "bio", "county_code", "updated_at"},
    # revision 0002: never moderation_state, owners, keys or decisions
    "problems": {
        "title",
        "statement",
        "affected_group",
        "niche_id",
        "country",
        "county_code",
        "embedding",
        "embed_model",
        "embed_version",
        "updated_at",
    },
    "problem_briefs": {"visibility", "budget_band", "deadline", "status", "updated_at"},
    "proposals": {
        "status",
        "current_version_id",
        "draft_version_id",
        "title",
        "niche_id",
        "country",
        "county_code",
        "maturity",
        "ask",
        "problem_statement",
        "impact_claims",
        "summary",
        "teaser_embedding",
        "embed_model",
        "embed_version",
        "tier2_policy",
        "raw_download_enabled",
        "published_at",
        "hidden_at",
        "updated_at",
    },
    "proposal_versions": {
        "status",
        "title",
        "niche_id",
        "country",
        "county_code",
        "maturity",
        "ask",
        "problem_statement",
        "impact_claims",
        "summary",
        "cert_id",
        "updated_at",
    },
    "proposal_attachments": {"sha256", "size_bytes", "av_status", "rerendered", "updated_at"},
    "tags": {"status", "updated_at"},
    "disclosure_grants": {
        "status",
        "counts_as_unlock",
        "billing_month",
        "granted_by",
        "granted_at",
        "revoked_at",
        "revoked_by",
        "updated_at",
    },
    "document_views": {"duration_bucket"},
    "moderation_cases": {"status", "reasons", "assigned_to", "decided_by", "decided_at", "updated_at"},
    # never the OTP columns (app_reissue_claim_otp(), app_confirm_claim_otp()) nor the DNS proof (dns_token is
    # written with the claim, dns_verified_at only by app_mark_claim_dns_verified())
    "org_claims": {
        "registration_no",
        "cr12_date",
        "kra_pin",
        "sector_register",
        "public_entity_requested",
        "document_keys",
        "status",
        "updated_at",
    },
    "directory_invitations": {"status", "reason", "approved_by", "sent_at", "updated_at"},
    # revision 0003: never state, end_reason, the stage times or lock_version (the chain's projection), nor the keys
    "engagements": {"contact_user_id", "contact_channel", "contact_by", "updated_at"},
    "agreements": {"ip_terms", "exclusivity", "deemed_acceptance_days", "status", "final_pdf_sha256", "updated_at"},
    "milestones": {"seq", "deliverable", "amount_kes_minor", "due_date", "review_window_bd", "state", "updated_at"},
    "payment_records": {"confirmed_by", "confirmed_amount_kes_minor"},  # the developer's one confirmation
    # revision 0005: never the keys, the organisation, the creator or a run's start and window; payments: no UPDATE
    "scout_agents": {
        "niches",
        "counties",
        "include_keywords",
        "exclude_keywords",
        "maturity",
        "budget_band",
        "min_fit",
        "frequency",
        "language",
        "recipients",
        "paused_at",
        "cursor_at",
        "cursor_proposal_id",
        "updated_at",
    },
    "agent_runs": {"status", "finished_at", "scanned_count", "matched_count", "error_code"},
    "agent_matches": {"feedback", "feedback_reason", "feedback_by", "feedback_at", "digest_sent_at"},
    "research_runs": {
        "status",
        "finished_at",
        "searches",
        "fetches",
        "input_tokens",
        "candidates",
        "discarded",
        "cost_usd",
        "stop_reason",
        "demo_fallback",
        "updated_at",
    },
    # revision 0006: marking read only; never the recipient, the organisation or the text (table-wide since 0001)
    "in_app_notifications": {"read_at"},
    # revision 0008: an upload joins its message and gets its scan verdict; a reader moves their marker; a saved
    # search is renamed, muted and advanced by the alert job (never its owner or query)
    "engagement_message_attachments": {"message_id", "av_status"},
    "engagement_message_reads": {"last_read_at"},
    "saved_searches": {"name", "alerts", "last_alerted_at"},
    # revision 0009: a developer's quiz settings and streak (never the key or its time)
    "quiz_profiles": {"leaderboard_opt_in", "current_streak", "best_streak", "last_played_on"},
}
APP_GRANTS: dict[str, set[str]] = {
    "users": {S, I, U},
    "sessions": {S, I, U, D},
    "login_tokens": {S, I, U, D},
    "login_attempts": {S, I, D},
    "api_tokens": {S, I, U},
    "auth_identities": {S, I, D},
    "email_suppressions": {S, I},
    "niches": {S},
    "regions": {S},
    "holidays": {S},
    "plans": {S},
    "organizations": {S, U},
    "memberships": {S, I, U},
    "invitations": {S, I, U},
    "org_niches": {S, I, D},
    "developer_profiles": {S, I, U},
    "developer_niches": {S, I, U, D},
    "consents": {S, I},
    "notification_preferences": {S, I, U, D},
    "in_app_notifications": {S, I, U},
    "subscriptions": {S, I},
    "notification_deliveries": {S, I, U},
    "audit_events": {S, I},
    "event_details": {S, I},
    # revision 0002
    "legal_templates": {S},
    "nda_templates": {S},
    "provenance_keys": {S},
    "problems": {S, I, U},
    "problem_sources": {S, I, D},
    "problem_briefs": {S, I, U},
    "brief_invitations": {S, I, D},
    "proposals": {S, I, U, D},
    "proposal_versions": {S, I, U, D},
    "proposal_problems": {S, I, D},
    "proposal_confidential": set(),  # docs/spec/06 6.1: no privilege at all; the Tier-2 roles only
    "proposal_confidential_embeddings": set(),
    "proposal_attachments": {S, I, U, D},
    "proposal_lsh_bands": {S, I, D},
    "originality_checks": {S, I},
    "provenance_records": {S},
    "chain_anchors": set(),
    "transparency_roots": {S},
    "attestations": {S, I},
    "tags": {S, I, U},
    "engagements": {S, I, U},  # INSERT and the contact columns from revision 0003
    "disclosure_grants": {S, I, U},
    "nda_acceptances": {S, I},
    "legal_acceptances": {S, I},
    "document_views": {S, I, U},
    "signal_events": {I},
    "moderation_cases": {S, I, U},
    "org_claims": {S, I, U},
    "directory_invitations": {S, I, U},
    "phone_verifications": {S, I},
    "kyc_reviews": {S, I},
    "llm_calls": {S, I},
    # revision 0003: the tracker (append-only tables: SELECT and INSERT only) and the dev/test clock
    "engagement_events": {S, I},
    "engagement_endorsements": {S, I},
    "agreements": {S, I, U},
    "milestones": {S, I, U, D},
    "signatures": {S, I},
    "payment_records": {S, I, U},
    "test_clock": {S},
    # revision 0005: scouts (the owner or admin configures), runs and matches (never deleted by the app), research runs
    # (staff admin), payments (status and subscription only through the definers: no UPDATE, no DELETE)
    "scout_agents": {S, I, U, D},
    "agent_runs": {S, I, U},
    "agent_matches": {S, I, U},
    "research_runs": {S, I, U},
    "payments": {S, I},
    # revision 0006: the side states' notes (append-only: SELECT and INSERT only, the INSERT without created_at)
    "engagement_notes": {S, I},
    # revision 0008: the thread (messages append-only; a staged upload is the uploader's to delete), the shortlist (a
    # working list: no UPDATE) and saved searches
    "engagement_messages": {S, I},
    "engagement_message_attachments": {S, I, U, D},
    "engagement_message_reads": {S, I, U},
    "org_shortlist": {S, I, D},
    "saved_searches": {S, I, U, D},
    # revision 0009: the quiz (sets and questions inserted by the job, decided and pulled only through the definers;
    # attempts append-only; flags only through app_flag_question; a developer's own profile)
    "quiz_sets": {S, I},
    "quiz_questions": {S, I},  # SELECT column-scoped: never answer or why (app_quiz_answers)
    "quiz_attempts": {S, I},
    "quiz_flags": {S},
    "quiz_profiles": {S, I, U},
}
# Every other runtime role: its whole matrix (table -> privileges) and its column-scoped UPDATEs.
ROLE_GRANTS: dict[str, dict[str, set[str]]] = {
    "aggregate_worker": {"signal_events": {S}},
    "audit_reader": {"audit_events": {S}, "chain_anchors": {S}},
    "tier2_reader": {"proposal_confidential": {S, I, U}},
    "provenance_worker": {
        "proposal_versions": {S, U},
        "proposal_confidential": {S, U},
        "provenance_records": {S, I, U},
        "provenance_keys": {S},
        "chain_anchors": {I},
        "transparency_roots": {I},
    },
    "tier2_embed_worker": {"proposal_confidential": {S}, "proposal_confidential_embeddings": {I}},
    "tier2_moderation": {"proposal_confidential": {S}, "proposal_confidential_embeddings": {S}},
    "dsr_exporter": {"proposal_confidential": {S}},
}
ROLE_COLUMN_UPDATES: dict[str, dict[str, set[str]]] = {
    "tier2_reader": {"proposal_confidential": {"ciphertext", "nonce", "wrapped_dek", "kms_key_id", "updated_at"}},
    "provenance_worker": {
        "proposal_versions": {"content_hash", "prev_version_hash", "manifest_version", "updated_at"},
        "proposal_confidential": {"manifest_ciphertext", "manifest_nonce", "updated_at"},
        "provenance_records": {
            "signature",
            "key_id",
            "status",
            "tsa_token",
            "tsa_time",
            "tsa_serial",
            "tsa_url",
            "ots_proof",
            "evidence_s3_key",
        },
    },
}

# signature -> (SECURITY DEFINER?, roles that may EXECUTE it). Trigger functions: nobody.
FUNCTIONS: dict[str, tuple[bool, set[str]]] = {
    "uuid7()": (False, {"bridge_app"}),
    "app_user_id()": (False, {"bridge_app", *TIER2_ROLES}),
    "app_org_id()": (False, {"bridge_app"}),
    "app_is_member(uuid, org_role[])": (True, {"bridge_app"}),
    "app_create_organization(uuid, org_kind, text, citext, text)": (True, {"bridge_app"}),
    "app_event_accepts_details(uuid)": (True, {"bridge_app"}),
    "audit_events_chain()": (True, set()),
    "audit_block_mutation()": (False, set()),
    # revision 0002
    "app_is_staff(staff_role[])": (True, {"bridge_app", "tier2_moderation"}),
    "app_reasons_are_valid(text[], integer)": (False, {"bridge_app"}),
    "app_current_legal_template(legal_template_kind)": (False, {"bridge_app"}),
    "app_current_nda_template(nda_kind)": (False, {"bridge_app"}),
    "app_owns_version(uuid)": (True, {"provenance_worker"}),
    "app_subject_digest(uuid, bytea)": (True, {"bridge_app", "provenance_worker"}),
    "app_tier2_granted(uuid, uuid, uuid)": (True, {"bridge_app", "tier2_reader"}),
    "app_held_tag_count(uuid)": (True, {"bridge_app"}),
    "app_confirm_phone_otp(uuid, bytea)": (True, {"bridge_app"}),
    "app_decide_kyc(uuid, boolean, text, text, text, text, boolean)": (True, {"bridge_app"}),
    "app_kyc_purge_due()": (True, {"bridge_app"}),
    "app_mark_kyc_images_purged(uuid)": (True, {"bridge_app"}),
    "app_moderate_proposal(uuid, moderation_state)": (True, {"bridge_app"}),
    "app_moderate_problem(uuid, moderation_state, problem_status)": (True, {"bridge_app"}),
    "app_hold_proposal(uuid)": (True, {"bridge_app"}),
    "app_hold_problem(uuid)": (True, {"bridge_app"}),
    "app_open_moderation_case(text, uuid, text[], moderation_source, jsonb)": (
        True,
        {"bridge_app", "tier2_moderation"},  # tier2_moderation: the Tier-2 similarity job
    ),
    "app_confirm_claim_otp(uuid, bytea)": (True, {"bridge_app"}),
    "app_mark_claim_dns_verified(uuid)": (True, {"bridge_app"}),
    "app_approve_claim_e1(uuid)": (True, {"bridge_app"}),
    "app_decide_claim(uuid, boolean, text)": (True, {"bridge_app"}),
    "app_staff_remove_membership(uuid, text)": (True, {"bridge_app"}),
    "app_delist_org(uuid)": (True, {"bridge_app"}),
    "app_opt_out_org_invitations(uuid)": (True, {"bridge_app"}),
    "app_llm_spend_usd(timestamp with time zone)": (True, {"bridge_app"}),
    "app_llm_call_inputs(uuid)": (True, {"bridge_app"}),
    "app_llm_batch_owned(character varying)": (True, {"bridge_app"}),  # batch_poll, before fetching results
    "app_llm_settle_batch_item(character varying, character varying, uuid, character varying, character varying,"
    " character varying, integer, integer, integer, integer, numeric, integer, character varying,"
    " character varying, character varying, jsonb)": (True, {"bridge_app"}),  # batch_poll settles each item
    "app_add_niche(text, text, text, text)": (True, {"bridge_app"}),
    "app_audit_chain_heads()": (True, {"provenance_worker"}),
    "app_unanchored_chain_heads()": (True, {"provenance_worker"}),
    "tags_guard()": (False, set()),
    "proposals_guard()": (True, set()),
    "app_reissue_claim_otp(uuid, bytea, timestamp with time zone)": (True, {"bridge_app"}),
    "org_claims_guard()": (True, set()),
    "org_claims_dns_guard()": (False, set()),
    "org_claims_status_guard()": (False, set()),
    "app_claim_competes(uuid, uuid)": (False, set()),  # called only inside the claim functions and org_claims_guard()
    "app_relabel_open_claims(uuid)": (False, set()),  # the claim functions and memberships_claims_relabel()
    "app_seat_claimant(uuid, uuid)": (False, set()),  # app_decide_claim() and app_approve_claim_e1()
    "memberships_claims_relabel()": (True, set()),
    "llm_calls_batch_guard()": (True, set()),
    "phone_verifications_guard()": (False, set()),
    "evidence_time_guard()": (False, set()),
    "chain_anchors_guard()": (True, set()),
    "provenance_records_hash_guard()": (True, set()),
    "transparency_roots_guard()": (False, set()),
    "block_mutation()": (False, set()),
    "proposal_versions_guard()": (True, set()),
    "proposal_confidential_guard()": (True, set()),
    "provenance_records_guard()": (False, set()),
    "proposal_attachments_guard()": (True, set()),
    # revision 0003
    "app_event_payload_is_valid(jsonb)": (False, {"bridge_app"}),  # ck_engagement_events_payload_holds_ids_and_codes
    "app_clock_now()": (False, {"bridge_app"}),
    "app_set_test_clock(interval)": (True, {"bridge_app"}),  # the test-clock router (dev, test and staging only)
    "engagement_event_canonical(engagement_events)": (False, set()),  # the chain trigger only
    "engagement_main_path_predecessors(engagement_state)": (False, set()),  # the chain trigger only
    "tracker_engagement_visible()": (False, set()),  # SECURITY INVOKER: the caller's RLS decides
    "engagements_members()": (True, set()),
    "engagement_endorsements_totp()": (True, set()),
    "signatures_totp()": (True, set()),
    "engagement_events_chain()": (True, set()),
    "engagement_events_project()": (True, set()),
    "engagements_guard()": (True, set()),
    "engagements_genesis()": (True, set()),
    "engagement_endorsements_guard()": (True, set()),
    "agreements_guard()": (True, set()),
    "milestones_guard()": (True, set()),
    "signatures_guard()": (True, set()),
    "payment_records_guard()": (True, set()),
    # revision 0004
    "app_llm_calls_since(character varying, timestamp with time zone)": (
        True,
        {"bridge_app"},  # SqlLedger.calls_since: a free slot's daily request cap, platform-wide (a count only)
    ),
    # revision 0005
    "app_uuid_set_is_valid(uuid[], integer, integer)": (False, {"bridge_app"}),  # scout_agents CHECKs
    "app_text_set_is_valid(text[], integer, integer)": (False, {"bridge_app"}),  # scout_agents and problems CHECKs
    "app_scouts_due(timestamp with time zone, scout_frequency, uuid)": (True, {"bridge_app"}),  # the scouts.scan job
    "app_create_research_candidate(uuid, text, text, text, text, numeric, text[], jsonb)": (True, {"bridge_app"}),
    "app_settle_payment(uuid, payment_status, text)": (True, {"bridge_app"}),
    "app_activate_paid_subscription(uuid)": (True, {"bridge_app"}),
    # Cross-organisation counts only; owned by bridge_owner (aggregate_worker cannot own it: revision 0005 docstring).
    "app_trend_aggregates(timestamp with time zone, timestamp with time zone)": (True, {"bridge_app"}),
    "app_research_source_is_valid(jsonb)": (False, set()),  # app_create_research_candidate() only
    "app_is_payment_subject(uuid, uuid)": (False, set()),  # the payment definers only
    "scout_row_visible()": (False, set()),  # SECURITY INVOKER: the caller's RLS decides
    "agent_matches_feedback_guard()": (False, set()),
    "research_runs_guard()": (False, set()),
    "payments_guard()": (False, set()),
    "problems_research_guard()": (True, set()),
    "scout_agents_recipients()": (True, set()),
    # revision 0006 (app_moderate_problem is replaced in place: same signature, definer and callers)
    "engagement_notes_redaction_guard()": (False, set()),  # SECURITY INVOKER: current_user is the writer (D-54)
    "engagement_notes_latest_event()": (True, set()),  # locks the engagement and reads the chain's head
    "app_brief_problem_is_public(uuid)": (True, {"bridge_app"}),
    "app_xid_is_current(xid)": (
        False,
        {"bridge_app"},
    ),  # the notes' INSERT policy: an event of this transaction  # the public read of problem_briefs (no recursion)
    "problem_briefs_status_guard()": (False, set()),  # SECURITY INVOKER: the caller's RLS reads the problem
    "problems_brief_text_guard()": (False, set()),
    # revision 0007: revision 0002's app_close_tag(uuid) with a status (withdrawn, or expired with its engagement)
    "app_close_tag(uuid, tag_status)": (True, {"bridge_app"}),
    # the engagements.expire job with no user bound: the engagements the clock may act on, ids only
    "app_engagements_due_for_expiry(timestamp with time zone)": (True, {"bridge_app"}),
    # revision 0008: the thread's gate, append-only guard, attachment guard and caps (triggers: nobody)
    "engagement_thread_open()": (True, set()),  # locks the engagement and reads the chain
    "engagement_messages_redaction_guard()": (False, set()),  # SECURITY INVOKER: current_user is the writer (D-54)
    "engagement_message_attachments_guard()": (False, set()),  # SECURITY INVOKER: the uploader reads their message
    "engagement_message_attachments_cap()": (True, set()),
    "saved_searches_cap()": (True, set()),
    "app_org_sees_proposal(uuid, uuid)": (True, {"bridge_app"}),  # the shortlist's INSERT policy and the API
    "app_saved_searches_due(timestamp with time zone)": (True, {"bridge_app"}),  # the alert job, no user bound
    "app_purge_stale_message_uploads(timestamp with time zone)": (True, {"bridge_app"}),  # the purge job, ditto
    "app_report_message(uuid, text[])": (True, {"bridge_app"}),  # a party's report of one message (fixed limit)
    "app_reported_message(uuid)": (True, {"bridge_app"}),  # staff admin|moderator read the reported message
    # revision 0009: the quiz (triggers and internal functions: nobody)
    "app_nairobi_today()": (False, {"bridge_app"}),  # the policies, the API and the job
    "app_is_developer()": (True, {"bridge_app"}),  # the policies and the API
    "quiz_attempt_score(uuid, smallint[])": (False, set()),  # the attempts' triggers and the rescore
    "quiz_rescore_set(uuid)": (False, set()),  # the definer functions below
    "app_rescore_quiz_set(uuid)": (True, {"bridge_app"}),  # staff admin, or a job with no user bound
    "app_decide_quiz_set(uuid, text)": (True, {"bridge_app"}),  # staff admin
    "app_set_quiz_question_status(uuid, text, text)": (True, {"bridge_app"}),  # staff admin
    "app_flag_question(uuid, text, text)": (True, {"bridge_app"}),  # a developer (fixed limits)
    "app_quiz_answers(uuid)": (True, {"bridge_app"}),  # after the caller's attempt, or staff admin
    "app_quiz_set_stats(uuid)": (True, {"bridge_app"}),  # staff admin: a set's attempts in aggregate only
    "app_quiz_set_detail(uuid)": (True, {"bridge_app"}),  # staff admin: a set's decision and generating call
    "app_quiz_board()": (True, {"bridge_app"}),  # a developer
    "app_quiz_day_taken(date)": (True, {"bridge_app"}),  # the quiz job, no user bound
    "app_quiz_recent_prompt_hashes(date)": (True, {"bridge_app"}),  # the quiz job, no user bound
    "quiz_sets_guard()": (False, set()),
    "quiz_questions_guard()": (True, set()),  # the job (no user bound) reads no set
    "quiz_attempts_score()": (True, set()),  # reads the answers
    "quiz_attempts_guard()": (False, set()),
}
PINNED_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"

# Temporary objects an attacker would plant (one statement each: psycopg sends parameterised queries singly).
SHADOWING_ATTACK = (
    "CREATE FUNCTION pg_temp.trap(v anyelement) RETURNS boolean LANGUAGE plpgsql AS"
    " $$ BEGIN RAISE EXCEPTION USING MESSAGE = concat('hijacked as ', current_user); END $$",
    "CREATE DOMAIN pg_temp.text AS pg_catalog.text CHECK (pg_temp.trap(VALUE))",
    "CREATE DOMAIN pg_temp.uuid AS pg_catalog.uuid CHECK (pg_temp.trap(VALUE))",
    "CREATE DOMAIN pg_temp.bytea AS pg_catalog.bytea CHECK (pg_temp.trap(VALUE))",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ZERO_HASH = bytes(32)

INSERT_EVENT = sa.text(
    "INSERT INTO audit_events (id, chain_id, actor_kind, actor_user_id, org_id, action, subject_type, subject_id,"
    " payload, seq, prev_hash, event_hash)"
    " VALUES (:id, :chain, CAST(:actor_kind AS audit_actor), :actor, :org, :action, :subject_type, :subject_id,"
    " CAST(:payload AS jsonb),"
    " 999, '\\x00'::bytea, '\\x00'::bytea)"  # seq and hashes sent by a client are overwritten by the trigger
)
SELECT_CHAIN = sa.text(
    "SELECT id, chain_id, seq, occurred_at, actor_kind::text AS actor_kind, actor_user_id, org_id, action,"
    " subject_type, subject_id, payload::text AS payload_text, prev_hash, event_hash"
    " FROM audit_events WHERE chain_id = :chain ORDER BY seq"
)


def tenancy(table: sa.Table) -> Tenancy:
    return Tenancy(table.info["tenancy"])


def tenant_tables() -> list[str]:
    return sorted(name for name, table in TABLES.items() if tenancy(table) in RLS_TENANCIES)


def event_params(chain: str, actor: UUID | None, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "chain": chain,
        "actor_kind": "user",
        "actor": actor,
        "org": None,
        "action": "test.event",
        "subject_type": "test",
        "subject_id": uuid7(),
        "payload": json.dumps({"n": 1, "note": "pipes | inside the payload are fine"}),
    }
    params.update(overrides)
    return params


def canonical(row: sa.Row[Any]) -> bytes:
    """The canonical form hashed by audit_events_chain() (documented in revision 0001)."""

    def text(value: object) -> str:
        return "" if value is None else str(value)

    fields = [
        row.prev_hash.hex(),
        str(row.seq),
        str(row.id),
        row.chain_id,
        str((row.occurred_at - EPOCH) // timedelta(microseconds=1)),
        row.actor_kind,
        text(row.actor_user_id),
        text(row.org_id),
        row.action,
        text(row.subject_type),
        text(row.subject_id),
        row.payload_text,
    ]
    return "|".join(fields).encode("utf-8")


def assert_linked_chain(rows: list[sa.Row[Any]]) -> None:
    assert [row.seq for row in rows] == list(range(1, len(rows) + 1))
    assert rows[0].prev_hash == ZERO_HASH
    for previous, row in pairwise(rows):
        assert row.prev_hash == previous.event_hash
        assert row.occurred_at >= previous.occurred_at  # clock_timestamp() under the lock follows seq
    for row in rows:
        assert len(row.event_hash) == 32
        assert row.event_hash == hashlib.sha256(canonical(row)).digest()


@asynccontextmanager
async def rolled_back(engine: AsyncEngine, user_id: UUID | None = None) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back (the session database is shared)."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            if user_id is not None:
                await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
            yield conn
        finally:
            await transaction.rollback()


async def expect_error(conn: AsyncConnection, sql: str, match: str, params: dict[str, Any] | None = None) -> None:
    """Run ``sql`` in a savepoint, assert it fails with ``match``, and leave the outer transaction usable."""
    savepoint = await conn.begin_nested()
    with pytest.raises(sa.exc.DBAPIError, match=match):
        await conn.execute(sa.text(sql), params or {})
    await savepoint.rollback()


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql), params)).scalar_one()


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[sa.Row[Any]]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


# --- Migration round trip ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scratch_url(admin_url: URL) -> Iterator[URL]:
    """A database of its own for the round trip and for tests that must commit (audit rows are undeletable)."""
    name = f"bridge_mig_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        yield url
    finally:
        drop_database(admin_url, name)


def leftover_objects(url: URL) -> list[str]:
    """Objects in schema public that are neither Alembic's version table nor extension members."""
    queries = {
        "relation": "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace"
        " AND c.relname NOT LIKE 'alembic_version%' AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')",
        "type": "SELECT t.typname FROM pg_type t WHERE t.typnamespace = 'public'::regnamespace"
        " AND t.typtype IN ('e', 'c', 'd') AND (t.typrelid = 0 OR t.typtype = 'c')"
        " AND t.typname NOT LIKE 'alembic_version%' AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')",
        "function": "SELECT p.proname FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace"
        " AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
        "policy": "SELECT policyname FROM pg_policies WHERE schemaname = 'public'",
    }
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            return [f"{kind} {name}" for kind, sql in queries.items() for (name,) in conn.execute(sa.text(sql))]
    finally:
        engine.dispose()


# The shape of schema public that a revision may change: columns, constraints, indexes, RLS and policies, functions,
# triggers, enum labels and every ACL (tables, columns, functions). Extension members are left out.
_NOT_EXTENSION = (
    "NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = '{catalog}'::regclass AND d.objid = {oid}"
    " AND d.deptype = 'e')"
)
SNAPSHOT: dict[str, str] = {
    "columns": "SELECT c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)"
    " || CASE WHEN a.attnotnull THEN ' not null' ELSE '' END"
    " || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')"
    " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
    " LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
    " WHERE c.relnamespace = 'public'::regnamespace AND a.attnum > 0 AND NOT a.attisdropped"
    " AND " + _NOT_EXTENSION.format(catalog="pg_class", oid="c.oid"),
    "constraints": "SELECT conrelid::regclass::text || ' ' || conname || ' ' || pg_get_constraintdef(oid)"
    " FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND conrelid <> 0",
    "indexes": "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'",
    "rls": "SELECT relname || ' ' || relrowsecurity || ' ' || relforcerowsecurity FROM pg_class"
    " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'",
    "policies": "SELECT tablename || ' ' || policyname || ' ' || cmd || ' ' || roles::text || ' '"
    " || coalesce(qual, '') || ' ' || coalesce(with_check, '') FROM pg_policies WHERE schemaname = 'public'",
    "functions": "SELECT p.oid::regprocedure::text || ' ' || p.prosecdef || ' ' || coalesce(p.proconfig::text, '')"
    " || ' ' || md5(pg_get_functiondef(p.oid)) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace"
    " AND p.prokind = 'f' AND " + _NOT_EXTENSION.format(catalog="pg_proc", oid="p.oid"),
    "triggers": "SELECT tgrelid::regclass::text || ' ' || tgname || ' ' || tgfoid::regprocedure::text || ' ' || tgtype"
    " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
    " WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace",
    "enums": "SELECT t.typname || ' ' || string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) FROM pg_type t"
    " JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typnamespace = 'public'::regnamespace GROUP BY t.typname",
    "table_acl": "SELECT c.relname || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type FROM pg_class c"
    " CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE c.relnamespace = 'public'::regnamespace",
    "column_acl": "SELECT c.relname || '.' || t.attname || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type"
    " FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid CROSS JOIN LATERAL aclexplode(t.attacl) a"
    " WHERE c.relnamespace = 'public'::regnamespace AND NOT t.attisdropped",
    "function_acl": "SELECT p.oid::regprocedure::text || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type"
    " FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.pronamespace = 'public'::regnamespace"
    " AND " + _NOT_EXTENSION.format(catalog="pg_proc", oid="p.oid"),
}


def schema_snapshot(url: URL) -> dict[str, list[str]]:
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            return {kind: sorted(conn.execute(sa.text(sql)).scalars()) for kind, sql in SNAPSHOT.items()}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_without_drift(scratch_url: URL) -> None:
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0001"))
    at_0001 = schema_snapshot(scratch_url)
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0002"))
    at_0002 = schema_snapshot(scratch_url)
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0003"))
    at_0003 = schema_snapshot(scratch_url)
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0004"))
    at_0004 = schema_snapshot(scratch_url)
    assert set(at_0004["functions"]) - set(at_0003["functions"]), "0004 adds app_llm_calls_since"
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0005"))
    at_0005 = schema_snapshot(scratch_url)
    assert set(at_0005["policies"]) - set(at_0004["policies"]), "0005 adds the policies of its tables"
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0006"))
    at_0006 = schema_snapshot(scratch_url)
    assert set(at_0006["policies"]) - set(at_0005["policies"]), "0006 adds the policies of engagement_notes"
    assert set(at_0005["table_acl"]) - set(at_0006["table_acl"]), "0006 narrows the in-app UPDATE to read_at"
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0007"))
    at_0007 = schema_snapshot(scratch_url)
    changed = {kind for kind in SNAPSHOT if at_0007[kind] != at_0006[kind]}
    assert changed == {"functions", "function_acl"}, "0007 replaces app_close_tag, adds one function, nothing else"
    assert "app_close_tag(uuid,tag_status) bridge_app EXECUTE" in at_0007["function_acl"]
    assert "app_engagements_due_for_expiry(timestamp with time zone) bridge_app EXECUTE" in at_0007["function_acl"]
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0008"))
    at_0008 = schema_snapshot(scratch_url)
    changed = {kind for kind in SNAPSHOT if at_0008[kind] != at_0007[kind]}
    assert changed == set(SNAPSHOT) - {"enums"}, "0008 adds tables, functions and policies; no enum type"
    assert set(at_0007["policies"]) - set(at_0008["policies"]), "0008 narrows the app's report INSERT policy"
    assert "app_report_message(uuid,text[]) bridge_app EXECUTE" in at_0008["function_acl"]
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    run_alembic(scratch_url, command.check)  # raises AutogenerateDiffsDetected on drift from the ORM
    at_head = schema_snapshot(scratch_url)
    changed = {kind for kind in SNAPSHOT if at_head[kind] != at_0008[kind]}
    assert changed == set(SNAPSHOT) - {"enums"}, "0009 adds tables, functions, policies and grants; no enum type"
    for kind in SNAPSHOT:  # additive: every object of 0008 is still there, unchanged
        assert set(at_0008[kind]) <= set(at_head[kind]), kind
    assert "app_flag_question(uuid,text,text) bridge_app EXECUTE" in at_head["function_acl"]
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0008"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0009 leaves every object of 0008 exactly as it found it
        assert after[kind] == at_0008[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0007"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0008 leaves every object of 0007 exactly as it found it (the report policy included)
        assert after[kind] == at_0007[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0006"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0007 leaves every object of 0006 exactly as it found it (app_close_tag byte for byte)
        assert after[kind] == at_0006[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0005"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0006 leaves every object of 0005 exactly as it found it (the in-app grants included)
        assert after[kind] == at_0005[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0004"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0005 leaves every object of 0004 exactly as it found it (the problems grants included)
        assert after[kind] == at_0004[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0003"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0004 leaves every object of 0003 exactly as it found it
        assert after[kind] == at_0003[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0002"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0003 leaves every object of 0002 exactly as it found it
        assert after[kind] == at_0002[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0001"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0002 leaves every object of 0001 exactly as it found it
        assert after[kind] == at_0001[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "base"))
    assert leftover_objects(scratch_url) == []
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    run_alembic(scratch_url, command.check)


def test_concurrent_appends_to_one_chain_are_serialised(scratch_url: URL) -> None:
    """A second writer waits on the chain's advisory lock and links to the first writer's committed event."""
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    chain = f"test:{uuid4().hex}"
    engine = sa.create_engine(scratch_url, poolclass=sa.pool.NullPool)
    errors: list[BaseException] = []
    pid: list[int] = []

    def second_writer() -> None:
        try:
            with engine.begin() as conn:  # commits on exit
                conn.exec_driver_sql("SET LOCAL ROLE bridge_app")
                pid.append(conn.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
                conn.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system"))
        except BaseException as exc:  # reported by the main thread
            errors.append(exc)

    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND locktype = 'advisory' AND NOT granted")
    try:
        with engine.begin() as first:  # holds the chain lock until it commits on exit
            first.exec_driver_sql("SET LOCAL ROLE bridge_app")
            first.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system"))
            thread = threading.Thread(target=second_writer)
            thread.start()
            deadline = time.monotonic() + 60
            waiting = False
            while not waiting and time.monotonic() < deadline and thread.is_alive():
                time.sleep(0.1)
                if pid:
                    waiting = bool(first.execute(blocked, {"pid": pid[0]}).scalar_one())
            assert waiting, "the second writer did not wait on the chain's advisory lock"
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert not errors, errors
        with engine.connect() as conn:
            assert_linked_chain(list(conn.execute(SELECT_CHAIN, {"chain": chain}).all()))
    finally:
        engine.dispose()


# --- Harness ------------------------------------------------------------------------------------------------------


@pytest.fixture
def notes_race_url(admin_url: URL) -> Iterator[URL]:
    """A database of its own at head (the race commits; scratch_url belongs to the round trip, which an async test
    reordered ahead of it would leave at head)."""
    name = f"bridge_race_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


async def test_a_note_waits_for_an_append_in_flight_and_is_refused_once_it_commits(notes_race_url: URL) -> None:
    """Revision 0006 (the notes' review): the race the INSERT policy alone left open. The organisation's request
    (seq 2) is committed without its note while the note's transaction is already open; the developer's answer (seq 3)
    is appended and holds the engagement's row lock; the note for seq 2 then waits on that lock
    (engagement_notes_1_latest_event, FOR NO KEY UPDATE) and, once the answer commits, is refused: its event is no
    longer the latest. The policy's own check had passed under the snapshot taken before the answer committed."""
    owner, app = role_engine(notes_race_url, "bridge_owner"), role_engine(notes_race_url, "bridge_app")
    try:
        async with owner.begin() as conn:
            p = await tracker.parties(conn)
            await tracker.act(conn, p.developer)
            engagement = await tracker.engage(conn, p)
        async with app.connect() as noter, app.connect() as asker, app.connect() as answerer:
            await noter.begin()
            await tracker.act(noter, p.owner, p.org)  # the note's transaction starts before its event
            async with asker.begin():
                await tracker.act(asker, p.owner, p.org)
                await tracker.append(asker, engagement, p.owner, "owner", "request_info", "SUBMITTED", "INFO_REQUESTED")
            await answerer.begin()
            await tracker.act(answerer, p.developer)
            await tracker.append(
                answerer, engagement, p.developer, "developer", "answer_info", "INFO_REQUESTED", "SUBMITTED"
            )
            note = asyncio.create_task(
                noter.execute(
                    sa.text(
                        "INSERT INTO engagement_notes (id, engagement_id, event_seq, kind, body, created_by)"
                        " VALUES (:id, :e, 2, 'info_request', 'Which counties?', :by)"
                    ),
                    {"id": uuid7(), "e": engagement, "by": p.owner},
                )
            )
            await asyncio.sleep(0.5)
            assert not note.done(), "the note did not wait for the append in flight"
            await answerer.commit()
            with pytest.raises(sa.exc.DBAPIError, match="only while its event is the engagement's latest"):
                await note
            await noter.rollback()
            # The policy's half (ev.xmin): a note from any transaction but its event's is refused, even while the event
            # is the latest, whether the note's transaction was opened before the event's (the actor's own earlier
            # transaction) or after it.
            other = (
                "INSERT INTO engagement_notes (id, engagement_id, event_seq, kind, body, created_by)"
                " VALUES (uuid7(), :e, 4, 'info_request', 'Which counties?', :by)"
            )
            await noter.begin()
            await tracker.act(noter, p.owner, p.org)  # opened before the event
            async with asker.begin():
                await tracker.act(asker, p.owner, p.org)
                await tracker.append(asker, engagement, p.owner, "owner", "request_info", "SUBMITTED", "INFO_REQUESTED")
            await expect_error(noter, other, "row-level security", {"e": engagement, "by": p.owner})
            await noter.rollback()
            async with noter.begin():
                await tracker.act(noter, p.owner, p.org)  # opened after it
                await expect_error(noter, other, "row-level security", {"e": engagement, "by": p.owner})
    finally:
        await owner.dispose()
        await app.dispose()


async def test_role_engines_keep_their_role_across_transactions(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    aggregate_engine: AsyncEngine,
    audit_reader_engine: AsyncEngine,
) -> None:
    """A rolled-back transaction must not undo an engine's SET ROLE (else tests would run as the superuser)."""
    engines = {
        "bridge_app": app_engine,
        "bridge_owner": owner_engine,
        "aggregate_worker": aggregate_engine,
        "audit_reader": audit_reader_engine,
    }
    current_user = sa.text("SELECT current_user")
    for role, engine in engines.items():
        for _ in range(3):
            async with rolled_back(engine) as conn:
                assert (await conn.execute(current_user)).scalar_one() == role
        async with engine.connect() as conn:
            assert (await conn.execute(current_user)).scalar_one() == role
            await conn.commit()
            assert (await conn.execute(current_user)).scalar_one() == role


# --- Classification and RLS coverage (generated from the ORM metadata) --------------------------------------------


async def test_every_table_is_declared_with_a_tenancy(owner_engine: AsyncEngine) -> None:
    found = await rows(
        owner_engine,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')",
    )
    names = {row.relname for row in found}
    undeclared = {n for n in names if n != "alembic_version" and not n.startswith("procrastinate_")} - set(TABLES)
    assert undeclared == set(), f"tables without an ORM model and tenancy: {sorted(undeclared)}"
    assert set(TABLES) <= names
    for table in TABLES.values():
        assert "tenancy" in table.info, f"{table.name} declares no tenancy"
        tenancy(table)  # a valid Tenancy value


@pytest.mark.parametrize("table", sorted(TABLES))
async def test_rls_follows_the_declared_tenancy(owner_engine: AsyncEngine, table: str) -> None:
    (row,) = await rows(
        owner_engine,
        "SELECT c.relrowsecurity, c.relforcerowsecurity, (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)"
        " AS policies FROM pg_class c WHERE c.oid = to_regclass(:t)",
        t=f"public.{table}",
    )
    if tenancy(TABLES[table]) in RLS_TENANCIES:
        assert row.relrowsecurity, f"{table}: RLS is not enabled"
        assert not row.relforcerowsecurity, f"{table}: RLS must be ENABLED, not FORCED (owner helpers bypass it)"
        assert row.policies >= 1, f"{table}: no policy"
    else:
        assert not row.relrowsecurity, f"{table}: global/system tables have no RLS"
        assert row.policies == 0


# Held on the table or on any of its columns (column-scoped UPDATE grants count). DELETE, TRUNCATE and TRIGGER exist
# only at table level.
HOLDS_PRIVILEGE = (
    "CASE WHEN {p} IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')"
    " THEN has_any_column_privilege({r}, 'public.' || {t}, {p})"
    " ELSE has_table_privilege({r}, 'public.' || {t}, {p}) END"
)


@pytest.mark.parametrize("table", tenant_tables())
async def test_every_command_granted_on_an_rls_table_has_a_policy(owner_engine: AsyncEngine, table: str) -> None:
    """For every runtime role (bridge_app and the Tier-2 roles alike): a granted command without a policy for that
    role would silently match no row, so the grant and the policy must come together."""
    found = await rows(
        owner_engine,
        "SELECT r.name AS role, p.name AS privilege, (SELECT count(*) FROM pg_policies pol"
        " WHERE pol.schemaname = 'public' AND pol.tablename = CAST(:t AS name) AND pol.cmd IN (p.name, 'ALL')"
        " AND CAST(r.name AS name) = ANY (pol.roles)) AS policies"
        " FROM unnest(CAST(:roles AS text[])) AS r(name) CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(name)"
        " WHERE " + HOLDS_PRIVILEGE.format(r="CAST(r.name AS name)", t="CAST(:t AS text)", p="p.name"),
        t=table,
        roles=list(RUNTIME_ROLES),
        privileges=[S, I, U, D],
    )
    uncovered = sorted(f"{row.role} may {row.privilege}" for row in found if row.policies == 0)
    assert uncovered == [], f"{table}: no policy covers {uncovered}"


@pytest.mark.parametrize("table", tenant_tables())
async def test_no_policy_is_granted_to_a_role_without_the_privilege(owner_engine: AsyncEngine, table: str) -> None:
    """The reverse: every policy names a runtime role that holds its command (no stale or misnamed policy)."""
    found = await rows(
        owner_engine,
        "SELECT pol.policyname, pol.cmd, CAST(r.role AS text) AS role, "
        + HOLDS_PRIVILEGE.format(r="r.role", t="CAST(:t AS text)", p="pol.cmd")
        + " AS held FROM pg_policies pol CROSS JOIN LATERAL unnest(pol.roles) AS r(role)"
        " WHERE pol.schemaname = 'public' AND pol.tablename = CAST(:t AS name)",
        t=table,
    )
    assert found, f"{table}: no policy"
    for policy in found:
        assert policy.role in RUNTIME_ROLES, f"{table}.{policy.policyname} is for {policy.role}"
        assert policy.held, f"{table}.{policy.policyname}: {policy.role} does not hold {policy.cmd}"


# --- Grants and roles ---------------------------------------------------------------------------------------------


async def privileges_of(engine: AsyncEngine, role: str) -> dict[str, set[str]]:
    found = await rows(
        engine,
        "SELECT t.name AS table_name, p.name AS privilege"
        " FROM unnest(CAST(:tables AS text[])) AS t(name) CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(name)"
        " WHERE " + HOLDS_PRIVILEGE.format(r="CAST(:role AS name)", t="t.name", p="p.name"),
        tables=sorted(TABLES),
        privileges=list(PRIVILEGES),
        role=role,
    )
    held: dict[str, set[str]] = {}
    for row in found:
        held.setdefault(row.table_name, set()).add(row.privilege)
    return held


async def test_bridge_app_grants_are_exactly_the_matrix(owner_engine: AsyncEngine) -> None:
    assert set(APP_GRANTS) == set(TABLES), "every ORM table needs a row in the grant matrix"
    expected = {table: privileges for table, privileges in APP_GRANTS.items() if privileges}
    assert await privileges_of(owner_engine, "bridge_app") == expected


async def test_bridge_app_updates_only_the_allowed_columns(owner_engine: AsyncEngine) -> None:
    columns = [(name, column.name) for name, table in TABLES.items() for column in table.columns]
    found = await rows(
        owner_engine,
        "SELECT x.t AS table_name, x.c AS column_name"
        " FROM unnest(CAST(:tables AS text[]), CAST(:columns AS text[])) AS x(t, c)"
        " WHERE has_column_privilege('bridge_app', 'public.' || x.t, x.c, 'UPDATE')",
        tables=[table for table, _ in columns],
        columns=[column for _, column in columns],
    )
    updatable: dict[str, set[str]] = {}
    for row in found:
        updatable.setdefault(row.table_name, set()).add(row.column_name)
    expected = {
        name: APP_COLUMN_UPDATES.get(name, {column.name for column in table.columns})
        for name, table in TABLES.items()
        if U in APP_GRANTS[name]
    }
    assert updatable == expected
    for table in APP_COLUMN_UPDATES:  # column-scoped only, never the whole table
        assert await scalar(owner_engine, "SELECT has_table_privilege('bridge_app', :t, 'UPDATE')", t=table) is False
    assert not {"staff_role", "status", "email", "subject_salt"} & updatable["users"]
    org_protected = {"verification", "slug", "kind", "source", "public_entity", "verified_domain", "official_domains"}
    org_protected |= {"delisted_at", "invitations_opted_out_at", "e2_verified_at", "reverify_due_on", "suspended_at"}
    assert not org_protected & updatable["organizations"]
    assert not {"moderation_state", "owner_id"} & (updatable["proposals"] | updatable["problems"])
    registration = {"registered_at", "owner_handle", "content_hash", "prev_version_hash", "manifest_version"}
    assert not registration & updatable["proposal_versions"]  # the database's and provenance_worker's
    assert "closed_at" not in updatable["tags"]  # closing is app_close_tag() or tags_guard(), never reopening
    claim_protected = {"otp_verified_at", "claimant_user_id", "reviewed_by", "decided_at", "level", "domain"}
    claim_protected |= {"otp_hash", "otp_expires_at", "otp_attempts", "otp_reissues"}
    assert not claim_protected & updatable["org_claims"]
    profile_protected = {"verification_level", "handle", "profile_embedding", "embed_model", "embed_version"}
    assert not profile_protected & updatable["developer_profiles"]
    projection = {"state", "end_reason", "stage_entered_at", "stage_deadline_at", "ended_at", "lock_version"}
    keys = {"proposal_id", "org_id", "developer_id", "version_id", "origin"}
    assert not (projection | keys) & updatable["engagements"]  # the chain's projection is the database's (0003)
    assert "demo_account" not in updatable["users"]  # the owner's (D-37)
    assert not {"confirmed_at", "amount_kes_minor", "recorded_by", "recorded_at"} & updatable["payment_records"]


async def test_bridge_app_cannot_update_protected_columns(app_engine: AsyncEngine) -> None:
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        await conn.execute(sa.text("UPDATE users SET display_name = 'Renamed' WHERE id = :id"), {"id": user_id})
        for column, value in (("staff_role", "'admin'"), ("status", "'suspended'"), ("email", "'x@example.test'")):
            await expect_error(
                conn, f"UPDATE users SET {column} = {value} WHERE id = :id", "permission denied", {"id": user_id}
            )
        await conn.execute(
            sa.text("INSERT INTO developer_profiles (user_id, handle) VALUES (:id, :handle)"),
            {"id": user_id, "handle": f"dev-{uuid4().hex[:12]}"},
        )
        by_user = {"id": user_id}
        await conn.execute(sa.text("UPDATE developer_profiles SET headline = 'Builder' WHERE user_id = :id"), by_user)
        for assignment in (
            "verification_level = 'd2'",
            "handle = 'taken'",
            "embed_model = 'x'",
            "embed_version = 'x'",
            "profile_embedding = NULL",
        ):
            await expect_error(
                conn, f"UPDATE developer_profiles SET {assignment} WHERE user_id = :id", "permission denied", by_user
            )
        await expect_error(conn, "UPDATE organizations SET verification = 'e2'", "permission denied")
        await expect_error(conn, "DELETE FROM memberships", "permission denied")
        await expect_error(conn, "UPDATE subscriptions SET status = 'active'", "permission denied")


async def test_append_only_tables_deny_update_delete_truncate_to_the_app(owner_engine: AsyncEngine) -> None:
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not await scalar(
            owner_engine, "SELECT has_table_privilege('bridge_app', 'audit_events', :p)", p=privilege
        )
    for privilege in ("UPDATE", "DELETE"):
        assert not await scalar(owner_engine, "SELECT has_table_privilege('bridge_app', 'consents', :p)", p=privilege)
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):  # revision 0006: the notes, like the events they explain
        assert not await scalar(
            owner_engine, "SELECT has_table_privilege('bridge_app', 'engagement_notes', :p)", p=privilege
        )
    held = "SELECT has_any_column_privilege('bridge_app', 'engagement_notes', 'UPDATE')"
    assert not await scalar(owner_engine, held)  # no column-scoped UPDATE either
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):  # revision 0008: the thread's messages, like the notes
        assert not await scalar(
            owner_engine, "SELECT has_table_privilege('bridge_app', 'engagement_messages', :p)", p=privilege
        )
    assert not await scalar(
        owner_engine, "SELECT has_any_column_privilege('bridge_app', 'engagement_messages', 'UPDATE')"
    )
    for table in ("quiz_attempts", "quiz_flags"):  # revision 0009: an attempt, a flag (rescores are the definer's)
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not await scalar(
                owner_engine, "SELECT has_table_privilege('bridge_app', :t, :p)", t=table, p=privilege
            )
        assert not await scalar(owner_engine, "SELECT has_any_column_privilege('bridge_app', :t, 'UPDATE')", t=table)


async def test_schema_v5_policies_are_exactly_the_notes_and_the_in_app_ones(owner_engine: AsyncEngine) -> None:
    """Revision 0006: the notes have one SELECT and one INSERT policy (append-only: nothing else). In-app notifications
    keep revision 0001's policies: a user updates only their own rows and cannot hand one to another user (USING and
    WITH CHECK), and the column grant, not a policy, keeps every column but read_at unchanged."""
    found = await rows(
        owner_engine,
        "SELECT tablename, policyname, cmd, CAST(roles AS text[]) AS roles, qual, with_check FROM pg_policies"
        " WHERE schemaname = 'public' AND tablename IN ('engagement_notes', 'in_app_notifications')",
    )
    assert {(row.tablename, row.policyname, row.cmd) for row in found} == {
        ("engagement_notes", "bridge_app_select", "SELECT"),
        ("engagement_notes", "bridge_app_insert", "INSERT"),
        ("in_app_notifications", "bridge_app_select", "SELECT"),
        ("in_app_notifications", "bridge_app_insert", "INSERT"),
        ("in_app_notifications", "bridge_app_update", "UPDATE"),
    }
    assert {role for row in found for role in row.roles} == {"bridge_app"}
    (update,) = (row for row in found if row.cmd == "UPDATE")
    assert update.qual == update.with_check == "(user_id = app_user_id())"


async def test_schema_v6_policies_are_exactly_the_planned_ones(owner_engine: AsyncEngine) -> None:
    """Revision 0008: messages have one SELECT and one INSERT policy (append-only); the other new tables the commands
    they are granted; every policy is bridge_app's. bridge_app's report INSERT on moderation_cases (revision 0002) is
    narrowed to every subject type but 'message' (app_report_message files those)."""
    found = await rows(
        owner_engine,
        "SELECT tablename, policyname, cmd, CAST(roles AS text[]) AS roles, with_check FROM pg_policies"
        " WHERE schemaname = 'public' AND tablename = ANY (:tables)",
        tables=[*V8_THREAD_TABLES, "org_shortlist", "saved_searches", "moderation_cases"],
    )
    commands = {
        "engagement_messages": ("SELECT", "INSERT"),
        "engagement_message_attachments": ("SELECT", "INSERT", "UPDATE", "DELETE"),
        "engagement_message_reads": ("SELECT", "INSERT", "UPDATE"),
        "org_shortlist": ("SELECT", "INSERT", "DELETE"),
        "saved_searches": ("SELECT", "INSERT", "UPDATE", "DELETE"),
        "moderation_cases": ("SELECT", "INSERT", "UPDATE"),
    }
    expected = {(table, f"bridge_app_{cmd.lower()}", cmd) for table, cmds in commands.items() for cmd in cmds}
    assert {(row.tablename, row.policyname, row.cmd) for row in found} == expected
    assert {role for row in found for role in row.roles} == {"bridge_app"}
    (report,) = (row for row in found if row.tablename == "moderation_cases" and row.cmd == "INSERT")
    assert report.with_check.endswith("AND ((subject_type)::text <> 'message'::text))")


async def test_schema_v7_policies_are_exactly_the_planned_ones(owner_engine: AsyncEngine) -> None:
    """Revision 0009: each quiz table has a policy for each command it is granted and no other; every policy is
    bridge_app's. Attempts and flags have no UPDATE or DELETE policy (append-only); flags have no INSERT policy
    (app_flag_question writes them); the job's inserts of sets and questions are for a session with no user bound."""
    found = await rows(
        owner_engine,
        "SELECT tablename, policyname, cmd, CAST(roles AS text[]) AS roles, with_check FROM pg_policies"
        " WHERE schemaname = 'public' AND tablename LIKE 'quiz%'",
    )
    commands = {
        "quiz_sets": ("SELECT", "INSERT"),
        "quiz_questions": ("SELECT", "INSERT"),
        "quiz_attempts": ("SELECT", "INSERT"),
        "quiz_flags": ("SELECT",),
        "quiz_profiles": ("SELECT", "INSERT", "UPDATE"),
    }
    expected = {(table, f"bridge_app_{cmd.lower()}", cmd) for table, cmds in commands.items() for cmd in cmds}
    assert {(row.tablename, row.policyname, row.cmd) for row in found} == expected
    assert {role for row in found for role in row.roles} == {"bridge_app"}
    job = {row.tablename: row.with_check for row in found if row.cmd == "INSERT"}
    assert job["quiz_sets"].startswith("((app_user_id() IS NULL) AND")
    assert job["quiz_questions"] == "(app_user_id() IS NULL)"


async def test_tags_keep_revision_0002s_policies(owner_engine: AsyncEngine) -> None:
    """Revision 0007 lets a tag expire through app_close_tag(tag, 'expired') only (its guard is in the function), so
    bridge_app's policies on tags stay revision 0002's: the developer's own UPDATE still sets nothing but withdrawn."""
    found = await rows(
        owner_engine,
        "SELECT policyname, cmd, CAST(roles AS text[]) AS roles, qual, with_check FROM pg_policies"
        " WHERE schemaname = 'public' AND tablename = 'tags'",
    )
    assert {(row.policyname, row.cmd) for row in found} == {
        ("bridge_app_select", "SELECT"),
        ("bridge_app_insert", "INSERT"),
        ("bridge_app_update", "UPDATE"),
    }
    assert {role for row in found for role in row.roles} == {"bridge_app"}
    (update,) = (row for row in found if row.cmd == "UPDATE")
    assert update.qual == "(developer_id = app_user_id())"
    assert update.with_check == "((developer_id = app_user_id()) AND (status = 'withdrawn'::tag_status))"


@pytest.mark.parametrize("role", sorted(ROLE_GRANTS))
async def test_other_runtime_roles_hold_exactly_their_matrix(owner_engine: AsyncEngine, role: str) -> None:
    """aggregate_worker reads only signal_events; audit_reader only the chain and its anchors; each Tier-2 role only
    what docs/spec/06 6.1 gives it. UPDATE is column-scoped wherever ROLE_COLUMN_UPDATES says so."""
    assert set(ROLE_GRANTS) | {"bridge_app"} == set(RUNTIME_ROLES)
    assert await privileges_of(owner_engine, role) == ROLE_GRANTS[role]
    for table, columns in ROLE_COLUMN_UPDATES.get(role, {}).items():
        found = await rows(
            owner_engine,
            "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
            " WHERE has_column_privilege(CAST(:role AS name), 'public.' || CAST(:t AS text), c.name, 'UPDATE')",
            columns=[column.name for column in TABLES[table].columns],
            role=role,
            t=table,
        )
        assert {row.name for row in found} == columns, f"{role} UPDATE on {table}"
        whole = "SELECT has_table_privilege(CAST(:role AS name), CAST(:t AS text), 'UPDATE')"
        assert await scalar(owner_engine, whole, role=role, t=table) is False


async def test_roles_are_neither_superuser_nor_bypassrls(owner_engine: AsyncEngine) -> None:
    found = await rows(
        owner_engine,
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = ANY (:roles)",
        roles=list(ROLES),
    )
    assert {row.rolname for row in found} == set(ROLES)
    for row in found:
        assert not row.rolsuper, row.rolname
        assert not row.rolbypassrls, row.rolname


@pytest.mark.parametrize("role", RUNTIME_ROLES)
async def test_runtime_roles_own_nothing(owner_engine: AsyncEngine, role: str) -> None:
    owned = await scalar(
        owner_engine,
        "SELECT (SELECT count(*) FROM pg_class WHERE relowner = r.oid)"
        " + (SELECT count(*) FROM pg_proc WHERE proowner = r.oid)"
        " + (SELECT count(*) FROM pg_type WHERE typowner = r.oid)"
        " + (SELECT count(*) FROM pg_namespace WHERE nspowner = r.oid)"
        " FROM pg_roles r WHERE r.rolname = :role",
        role=role,
    )
    assert owned == 0


async def test_every_table_is_owned_by_bridge_owner(owner_engine: AsyncEngine) -> None:
    owners = await rows(
        owner_engine,
        "SELECT DISTINCT pg_get_userbyid(relowner) AS owner FROM pg_class"
        " WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p', 'S', 'v', 'm')",
    )
    assert {row.owner for row in owners} == {"bridge_owner"}


@pytest.mark.parametrize("signature", sorted(FUNCTIONS))
async def test_helper_functions_are_locked_down(owner_engine: AsyncEngine, signature: str) -> None:
    definer, callers = FUNCTIONS[signature]
    (row,) = await rows(
        owner_engine,
        "SELECT prosecdef, proconfig, pg_get_userbyid(proowner) AS owner FROM pg_proc"
        " WHERE oid = to_regprocedure(:sig)",
        sig=signature,
    )
    assert row.prosecdef is definer
    assert row.owner == "bridge_owner"
    assert row.proconfig == [PINNED_SEARCH_PATH]
    allowed = await rows(
        owner_engine,
        "SELECT r.name FROM unnest(CAST(:roles AS text[])) AS r(name)"
        " WHERE has_function_privilege(r.name, CAST(:sig AS text), 'EXECUTE')",
        roles=["public", *RUNTIME_ROLES],
        sig=signature,
    )
    assert {row.name for row in allowed} == callers, f"EXECUTE {signature}"


async def test_every_function_pins_search_path_with_pg_temp_last(owner_engine: AsyncEngine) -> None:
    """Every function of the revision (helpers, triggers, Procrastinate's), not only the listed helpers."""
    found = await rows(
        owner_engine,
        "SELECT p.oid::regprocedure::text AS signature, p.proconfig FROM pg_proc p"
        " WHERE p.pronamespace = 'public'::regnamespace AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
    )
    assert len(found) > len(FUNCTIONS)  # includes procrastinate_*
    unpinned = sorted(row.signature for row in found if row.proconfig != [PINNED_SEARCH_PATH])
    assert unpinned == []


@pytest.mark.parametrize("role", RUNTIME_ROLES)
async def test_runtime_roles_cannot_create_temporary_objects(owner_engine: AsyncEngine, role: str) -> None:
    privilege = "SELECT has_database_privilege(:r, current_database(), 'TEMPORARY')"
    assert await scalar(owner_engine, privilege, r=role) is False


async def test_pg_temp_shadowing_cannot_hijack_definer_functions(database_url: URL) -> None:
    """The attack the pinned search_path stops. bridge_app shadows uuid, text and bytea with temporary domains whose
    CHECK raises with current_user. With pg_temp unlisted it is searched first for types, so SECURITY DEFINER code
    (``v_user uuid`` in app_create_organization, ``bytea`` and ``::text`` in the audit trigger) resolved the domains
    and ran the CHECK as bridge_owner. TEMPORARY is granted inside the rolled-back transaction to show the pinned path
    holds on its own; a fresh backend makes sure no plan compiled before the domains existed hides a regression."""
    engine = role_engine(database_url, "bridge_owner", poolclass=sa.pool.NullPool)
    user_id, org_id = uuid7(), uuid7()
    try:
        async with rolled_back(engine) as conn:
            await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
            await expect_error(conn, "CREATE TEMP TABLE t (x int)", "permission denied to create temporary tables")
            await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))  # owns the database; the grant is rolled back
            database = (await conn.execute(sa.text("SELECT current_database()"))).scalar_one()
            await conn.execute(sa.text(f'GRANT TEMPORARY ON DATABASE "{database}" TO bridge_app'))
            await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
            await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
            await conn.execute(
                sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Victim')"),
                {"id": user_id, "email": f"{uuid4().hex}@example.test"},
            )
            for statement in SHADOWING_ATTACK:
                await conn.execute(sa.text(statement))
            # The trap is live: SQL without a pinned path resolves the temporary domain and runs its CHECK.
            await expect_error(conn, "SELECT CAST('x' AS text)", "hijacked as bridge_app")
            # Pinned functions never resolve it (before the fix each of these raised "hijacked as bridge_owner").
            await conn.execute(
                sa.text("SELECT app_create_organization(:id, 'company', 'Victim Ltd', CAST(:slug AS citext))"),
                {"id": org_id, "slug": f"victim-{uuid4().hex}"},
            )
            member = sa.text("SELECT app_is_member(:id, '{owner}')")
            assert (await conn.execute(member, {"id": org_id})).scalar_one() is True
            await conn.execute(sa.text("SELECT uuid7(), app_user_id(), app_org_id()"))
            await conn.execute(sa.text("SELECT app_llm_calls_since('m', now())"))  # revision 0004
            await conn.execute(sa.text("SELECT app_brief_problem_is_public(uuid7())"))  # revision 0006
            await conn.execute(sa.text("SELECT app_xid_is_current(CAST('3' AS xid))"))
            await expect_error(  # revision 0007: refused before it reads anything but the (missing) tag
                conn, "SELECT app_close_tag(uuid7(), 'expired')", "the developer or a member of the tagged organisation"
            )
            await expect_error(  # revision 0007: the expiry job's list, refused to a signed-in session
                conn, "SELECT count(*) FROM app_engagements_due_for_expiry(now())", "the engagements.expire job only"
            )
            # revision 0008: the shortlist's Inbox check (false: no such proposal), the alert job's list and the
            # purge (refused to a signed-in session), a report (refused: no such message) and the staff reader
            # (refused: not staff)
            inbox = sa.text("SELECT app_org_sees_proposal(:org, uuid7())")
            assert (await conn.execute(inbox, {"org": org_id})).scalar_one() is False
            await expect_error(conn, "SELECT count(*) FROM app_saved_searches_due(now())", "the saved-search alert job")
            await expect_error(
                conn, "SELECT count(*) FROM app_purge_stale_message_uploads(now())", "the stale-upload purge job"
            )
            await expect_error(
                conn, "SELECT * FROM app_report_message(uuid7(), ARRAY['spam'])", "no message of the caller's"
            )
            await expect_error(conn, "SELECT * FROM app_reported_message(uuid7())", "staff admin or moderator only")
            # revision 0005: the definers and CHECK helpers bridge_app may call
            await conn.execute(sa.text("SELECT count(*) FROM app_trend_aggregates(now() - interval '1 day', now())"))
            await conn.execute(sa.text("SELECT app_uuid_set_is_valid(ARRAY[uuid7()], 1, 5)"))
            await conn.execute(sa.text("SELECT app_text_set_is_valid(ARRAY['x'], 1, 5)"))
            await expect_error(
                conn, "SELECT app_settle_payment(uuid7(), 'failed', 'declined')", "no payment of the caller's"
            )
            await expect_error(conn, "SELECT app_activate_paid_subscription(uuid7())", "no payment of the caller's")
            await expect_error(conn, "SELECT count(*) FROM app_scouts_due(now(), 'daily')", "the scouts.scan job only")
            event_id = uuid7()
            await conn.execute(
                sa.text("INSERT INTO audit_events (id, chain_id, actor_kind, action) VALUES (:id, :c, 'system', 'x')"),
                {"id": event_id, "c": f"test:{uuid4().hex}"},
            )
            await conn.execute(sa.text("INSERT INTO event_details (event_id) VALUES (:id)"), {"id": event_id})
    finally:
        await engine.dispose()


ADD_PLAN = (
    'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits, is_default)'
    " VALUES (:id, :code, 'developer', 'Test plan', :price, 'month', '{}'::jsonb, :is_default)"
)


def plan_params(price: int, is_default: bool) -> dict[str, Any]:
    return {"id": uuid7(), "code": f"test-{uuid4().hex[:12]}", "price": price, "is_default": is_default}


async def test_self_serve_subscriptions_only_to_the_default_plan(owner_engine: AsyncEngine) -> None:
    user_id = uuid7()
    subscribe = (
        "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)"
        " VALUES (:id, :user, :plan, 'active', now())"
    )
    async with rolled_back(owner_engine) as conn:
        await add_user(conn, user_id)
        existing = "SELECT id FROM plans WHERE side = 'developer' AND is_default"
        default_id = (await conn.execute(sa.text(existing))).scalar_one_or_none()
        if default_id is None:  # the seed may already have one (config/plans.yaml `default: true`)
            default = plan_params(0, is_default=True)
            await conn.execute(sa.text(ADD_PLAN), default)
            default_id = default["id"]
        paid = plan_params(150_000, is_default=False)
        await conn.execute(sa.text(ADD_PLAN), paid)
        await expect_error(conn, ADD_PLAN, "uq_plans_default_side", plan_params(0, is_default=True))  # one per side

        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await act_as(conn, user_id)
        await expect_error(conn, subscribe, "row-level security", {"id": uuid7(), "user": user_id, "plan": paid["id"]})
        await conn.execute(sa.text(subscribe), {"id": uuid7(), "user": user_id, "plan": default_id})
        mine = sa.text("SELECT plan_id FROM subscriptions WHERE user_id = :user")
        assert (await conn.execute(mine, {"user": user_id})).scalars().all() == [default_id]


async def test_deleting_a_user_removes_their_user_only_deliveries(owner_engine: AsyncEngine) -> None:
    """ON DELETE CASCADE: SET NULL would violate has_recipient_scope and block the deletion (erasure, REQ-SEC-02)."""
    user_id = uuid7()
    async with rolled_back(owner_engine) as conn:
        await add_user(conn, user_id)
        await conn.execute(
            sa.text(
                "INSERT INTO notification_deliveries (id, user_id, kind, channel, to_address)"
                " VALUES (:id, :user, 'em7', 'email', 'x@example.test')"
            ),
            {"id": uuid7(), "user": user_id},
        )
        await conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        left = sa.text("SELECT count(*) FROM notification_deliveries WHERE user_id = :id")
        assert (await conn.execute(left, {"id": user_id})).scalar_one() == 0


async def test_enum_types_match_the_orm(owner_engine: AsyncEngine) -> None:
    declared: dict[str, list[str]] = {}
    for table in TABLES.values():
        for column in table.columns:
            column_type = column.type
            if isinstance(column_type, postgresql.ARRAY):
                column_type = column_type.item_type
            if isinstance(column_type, sa.Enum) and column_type.name:
                declared[column_type.name] = list(column_type.enums)
    found = await rows(
        owner_engine,
        "SELECT t.typname, array_agg(e.enumlabel::text ORDER BY e.enumsortorder) AS labels"
        " FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
        " WHERE t.typnamespace = 'public'::regnamespace AND t.typname NOT LIKE 'procrastinate%' GROUP BY t.typname",
    )
    assert {row.typname: list(row.labels) for row in found} == declared


# --- RLS helpers --------------------------------------------------------------------------------------------------


async def test_app_create_organization_makes_the_caller_owner(app_engine: AsyncEngine) -> None:
    org_id = uuid7()
    create = "SELECT app_create_organization(:id, 'company', 'Acme Ltd', CAST(:slug AS citext))"
    async with rolled_back(app_engine) as conn:
        await expect_error(conn, create, "app.user_id is not set", {"id": org_id, "slug": f"acme-{uuid4().hex}"})

    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await conn.execute(
            sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test Owner')"),
            {"id": user_id, "email": f"{uuid4().hex}@example.test"},
        )
        created = (await conn.execute(sa.text(create), {"id": org_id, "slug": f"acme-{uuid4().hex}"})).scalar_one()
        assert created == org_id
        org = (
            await conn.execute(
                sa.text("SELECT verification::text, source::text, created_by FROM organizations WHERE id = :id"),
                {"id": org_id},
            )
        ).one()
        assert tuple(org) == ("pending", "self_signup", user_id)
        membership = (
            await conn.execute(
                sa.text("SELECT roles::text[] AS roles, status::text AS status FROM memberships WHERE org_id = :id"),
                {"id": org_id},
            )
        ).one()
        assert (membership.roles, membership.status) == (["owner", "admin"], "active")
        member = sa.text("SELECT app_is_member(:id), app_is_member(:id, '{owner}'), app_is_member(:id, '{signatory}')")
        assert tuple((await conn.execute(member, {"id": org_id})).one()) == (True, True, False)
        await expect_error(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'sme', 'X', :slug, 'seed')",
            "permission denied",
            {"id": uuid7(), "slug": f"x-{uuid4().hex}"},
        )
        # Another user in the same transaction: not a member, and RLS hides the organisation and its roster.
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(uuid7())})
        assert (await conn.execute(member, {"id": org_id})).one()[0] is False
        for table, column in (("organizations", "id"), ("memberships", "org_id")):
            visible = sa.text(f"SELECT count(*) FROM {table} WHERE {column} = :id")
            assert (await conn.execute(visible, {"id": org_id})).scalar_one() == 0


async def act_as(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


async def add_user(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(
        sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test User')"),
        {"id": user_id, "email": f"{uuid4().hex}@example.test"},
    )


ADD_MEMBER = (
    "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS org_role[]))"
)
INVITE = (
    "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at)"
    " VALUES (:id, :org, :email, CAST(:roles AS org_role[]), :token, app_user_id(), now() + interval '7 days')"
)


def member_params(org_id: UUID, user_id: UUID, roles: str) -> dict[str, Any]:
    return {"id": uuid7(), "org": org_id, "user": user_id, "roles": roles}


def invite_params(org_id: UUID, roles: str) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "org": org_id,
        "email": f"{uuid4().hex}@example.test",
        "roles": roles,
        "token": uuid4().bytes,
    }


async def test_admins_cannot_grant_or_touch_protected_roles(app_engine: AsyncEngine) -> None:
    """Protected roles are owner and signatory. An admin who is not an owner cannot grant them (to themselves or
    anyone), invite with them, or change a membership that holds them; an owner can do all of it."""
    owner, admin, member, newcomer = uuid7(), uuid7(), uuid7(), uuid7()
    org_id = uuid7()
    rls = "row-level security"
    async with rolled_back(app_engine, owner) as conn:
        for user_id in (owner, admin, member, newcomer):
            await add_user(conn, user_id)
        await conn.execute(
            sa.text("SELECT app_create_organization(:id, 'sme', 'Roles Ltd', CAST(:slug AS citext))"),
            {"id": org_id, "slug": f"roles-{uuid4().hex}"},
        )
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, admin, "{admin}"))

        await act_as(conn, admin)
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, member, "{viewer}"))  # admins manage others
        invitation = invite_params(org_id, "{reviewer}")
        await conn.execute(sa.text(INVITE), invitation)
        own_roles = "UPDATE memberships SET roles = CAST(:roles AS org_role[]) WHERE org_id = :org AND user_id = :user"
        for protected in ("{owner,admin}", "{admin,signatory}"):  # no self-assignment of owner or signatory
            await expect_error(conn, own_roles, rls, {"roles": protected, "org": org_id, "user": admin})
        for protected in ("{owner}", "{viewer,signatory}"):
            await expect_error(conn, own_roles, rls, {"roles": protected, "org": org_id, "user": member})
            await expect_error(conn, ADD_MEMBER, rls, member_params(org_id, newcomer, protected))
            await expect_error(conn, INVITE, rls, invite_params(org_id, protected))
            await expect_error(
                conn,
                "UPDATE invitations SET roles = CAST(:roles AS org_role[]) WHERE id = :id",
                rls,
                {"roles": protected, "id": invitation["id"]},
            )
        # The owner's membership is invisible to the admin's UPDATE: no demotion, no removal.
        remove = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :user"
        assert (await conn.execute(sa.text(remove), {"org": org_id, "user": owner})).rowcount == 0

        await act_as(conn, owner)
        grant = await conn.execute(sa.text(own_roles), {"roles": "{viewer,signatory}", "org": org_id, "user": member})
        assert grant.rowcount == 1
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, newcomer, "{owner}"))
        await conn.execute(sa.text(INVITE), invite_params(org_id, "{owner}"))
        await conn.execute(sa.text(INVITE), invite_params(org_id, "{signatory}"))

        await act_as(conn, admin)  # a signatory's membership is now out of the admin's reach too
        assert (await conn.execute(sa.text(remove), {"org": org_id, "user": member})).rowcount == 0

        await act_as(conn, owner)
        promote = await conn.execute(sa.text(own_roles), {"roles": "{owner,admin}", "org": org_id, "user": admin})
        assert promote.rowcount == 1
        roles = await conn.execute(
            sa.text(
                "SELECT user_id, roles::text[] AS roles, status::text AS status FROM memberships WHERE org_id = :org"
            ),
            {"org": org_id},
        )
        assert {row.user_id: (row.roles, row.status) for row in roles} == {
            owner: (["owner", "admin"], "active"),
            admin: (["owner", "admin"], "active"),
            member: (["viewer", "signatory"], "active"),
            newcomer: (["owner"], "active"),
        }


# --- Audit chain (REQ-AUD-01) -------------------------------------------------------------------------------------


async def test_trigger_chains_seq_prev_hash_and_event_hash(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        for n in range(3):
            payload = json.dumps({"n": n, "amount_kes_minor": 150_000, "note": "a|b"})
            await conn.execute(INSERT_EVENT, event_params(chain, actor, payload=payload, subject_type=None))
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert len(chained) == 3
    assert_linked_chain(chained)


async def test_multi_row_insert_is_chained_in_order(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    first, second = event_params(chain, actor, action="test.first"), event_params(chain, actor, action="test.second")
    values = "(:id{n}, :chain, 'user', :actor, NULL, :action{n}, 'test', :subject_id{n}, '{{}}'::jsonb, 0, '', '')"
    sql = (
        "INSERT INTO audit_events (id, chain_id, actor_kind, actor_user_id, org_id, action, subject_type, subject_id,"
        f" payload, seq, prev_hash, event_hash) VALUES {values.format(n=1)}, {values.format(n=2)}"
    )
    params = {"chain": chain, "actor": actor}
    for n, event in ((1, first), (2, second)):
        params |= {f"id{n}": event["id"], f"action{n}": event["action"], f"subject_id{n}": event["subject_id"]}
    async with rolled_back(app_engine, actor) as conn:
        await conn.execute(sa.text(sql), params)
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert [row.action for row in chained] == ["test.first", "test.second"]
    assert_linked_chain(chained)


async def test_separator_in_chain_fields_is_rejected(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        for field in ("chain", "action", "subject_type"):
            params = event_params(chain, actor) | {field: "evil|field"}
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="may not contain"):
                await conn.execute(INSERT_EVENT, params)
            await savepoint.rollback()


async def test_empty_chain_fields_are_rejected_and_scoped_chain_ids_accepted(app_engine: AsyncEngine) -> None:
    actor = uuid7()
    async with rolled_back(app_engine, actor) as conn:
        for overrides in ({"chain": ""}, {"action": ""}, {"subject_type": ""}):
            params = event_params(f"test:{uuid4().hex}", actor) | overrides
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="violates check constraint"):
                await conn.execute(INSERT_EVENT, params)
            await savepoint.rollback()
        for chain in (f"org:{uuid7()}", f"user:{uuid7()}"):  # the app's per-scope chain ids
            await conn.execute(INSERT_EVENT, event_params(chain, actor))
            await conn.execute(INSERT_EVENT, event_params(chain, actor))
            assert_linked_chain(list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all()))


async def test_appends_outside_read_committed_are_refused(app_engine: AsyncEngine) -> None:
    """Under REPEATABLE READ the head read after the lock could be stale, so the trigger refuses by design."""
    for level in ("REPEATABLE READ", "SERIALIZABLE"):
        async with rolled_back(app_engine) as conn:
            await conn.execute(sa.text(f"SET TRANSACTION ISOLATION LEVEL {level}"))
            with pytest.raises(sa.exc.DBAPIError, match=f"must run at READ COMMITTED isolation, not {level}"):
                await conn.execute(INSERT_EVENT, event_params(f"test:{uuid4().hex}", None, actor_kind="system"))


async def test_app_cannot_update_delete_or_truncate_audit_events(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        await conn.execute(INSERT_EVENT, event_params(chain, actor))
        chain_filter = {"chain": chain}
        await expect_error(
            conn, "UPDATE audit_events SET action = 'x' WHERE chain_id = :chain", "permission denied", chain_filter
        )
        await expect_error(conn, "DELETE FROM audit_events WHERE chain_id = :chain", "permission denied", chain_filter)
        await expect_error(conn, "TRUNCATE audit_events", "permission denied")
        await expect_error(conn, "DELETE FROM event_details", "permission denied")
        await expect_error(conn, "UPDATE consents SET granted = true", "permission denied")
        await expect_error(conn, "DELETE FROM consents", "permission denied")


async def test_triggers_block_update_delete_truncate_even_for_the_owner(owner_engine: AsyncEngine) -> None:
    chain = f"test:{uuid4().hex}"
    params = event_params(chain, None)
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, params)
        await conn.execute(
            sa.text('INSERT INTO event_details (event_id, details) VALUES (:id, \'{"email": "a@example.test"}\')'),
            {"id": params["id"]},
        )
        by_id = {"id": params["id"]}
        await expect_error(conn, "UPDATE audit_events SET action = 'x' WHERE id = :id", "append-only", by_id)
        await expect_error(conn, "DELETE FROM audit_events WHERE id = :id", "append-only", by_id)
        # TRUNCATE audit_events alone stops at the event_details foreign key before any trigger runs; with both tables
        # listed, the audit_events trigger fires first and names its own table.
        await expect_error(
            conn, "TRUNCATE audit_events, event_details", "TRUNCATE on audit_events is not allowed: the audit log"
        )
        await expect_error(conn, "DELETE FROM event_details WHERE event_id = :id", "append-only", by_id)
        await expect_error(conn, "TRUNCATE event_details", "append-only")
        # event_details stays updatable by the owner: erasure overwrites personal data without touching the chain.
        await conn.execute(sa.text("UPDATE event_details SET details = '{}' WHERE event_id = :id"), by_id)
        assert_linked_chain(list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all()))


# pg_trigger.tgtype bits (src/include/catalog/pg_trigger.h).
ROW, BEFORE, ON_INSERT, ON_DELETE, ON_UPDATE, ON_TRUNCATE = 1, 2, 4, 8, 16, 32
AUDIT_TRIGGERS = {
    ("audit_events", "audit_events_chain"): ("audit_events_chain", ROW | BEFORE | ON_INSERT),
    ("audit_events", "audit_events_no_update_delete"): ("audit_block_mutation", ROW | BEFORE | ON_DELETE | ON_UPDATE),
    ("audit_events", "audit_events_no_truncate"): ("audit_block_mutation", BEFORE | ON_TRUNCATE),
    ("event_details", "event_details_no_delete"): ("audit_block_mutation", ROW | BEFORE | ON_DELETE),
    ("event_details", "event_details_no_truncate"): ("audit_block_mutation", BEFORE | ON_TRUNCATE),
}


async def test_audit_triggers_are_installed_and_enabled(owner_engine: AsyncEngine) -> None:
    """Each table's own triggers, checked in the catalog (a statement can only show the first one that fires)."""
    found = await rows(
        owner_engine,
        "SELECT tgrelid::regclass::text AS table_name, tgname, tgfoid::regproc::text AS function, tgtype, tgenabled"
        " FROM pg_trigger WHERE NOT tgisinternal"
        " AND tgrelid IN ('public.audit_events'::regclass, 'public.event_details'::regclass)",
    )
    assert {(row.table_name, row.tgname): (row.function, row.tgtype) for row in found} == AUDIT_TRIGGERS
    assert {row.tgenabled for row in found} == {"O"}  # enabled for ordinary sessions, not disabled or replica-only


async def test_audit_visibility_for_the_app_and_the_reader(owner_engine: AsyncEngine) -> None:
    """One transaction, switching roles with SET LOCAL ROLE (the harness session user is a superuser)."""
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    count = sa.text("SELECT count(*) FROM audit_events WHERE chain_id = :chain")
    details = "INSERT INTO event_details (event_id) VALUES (:id)"
    own, other = event_params(chain, actor), event_params(chain, uuid7())
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, own)
        await conn.execute(INSERT_EVENT, other)

        await conn.execute(sa.text("SET LOCAL ROLE audit_reader"))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 2  # the verifier reads every event
        await expect_error(conn, "SELECT count(*) FROM event_details", "permission denied")  # but no personal data
        await expect_error(conn, details, "permission denied", {"id": own["id"]})

        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 0  # no tenant context: nothing
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(actor)})
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 1  # only the actor's own event
        await conn.execute(sa.text(details), {"id": own["id"]})
        await expect_error(conn, details, "row-level security", {"id": other["id"]})  # another user's event
        visible_details = sa.text("SELECT event_id FROM event_details WHERE event_id IN (:own, :other)")
        found = (await conn.execute(visible_details, {"own": own["id"], "other": other["id"]})).scalars().all()
        assert found == [own["id"]]  # reading them follows the event's visibility

        # An organisation's owners and admins see its events, whoever the actor was.
        org_id = uuid7()
        await conn.execute(
            sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test Admin')"),
            {"id": actor, "email": f"{uuid4().hex}@example.test"},
        )
        await conn.execute(
            sa.text("SELECT app_create_organization(:id, 'sme', 'Org Ltd', CAST(:slug AS citext))"),
            {"id": org_id, "slug": f"org-{uuid4().hex}"},
        )
        await conn.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system", org=org_id))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 2


async def test_system_event_and_details_need_no_user(app_engine: AsyncEngine) -> None:
    """A job without app.user_id appends a system event and its details in one transaction."""
    chain = f"test:{uuid4().hex}"
    event = event_params(chain, None, actor_kind="system")
    async with rolled_back(app_engine) as conn:
        await conn.execute(INSERT_EVENT, event)
        await conn.execute(
            sa.text('INSERT INTO event_details (event_id, details) VALUES (:id, \'{"note": "nightly job"}\')'),
            {"id": event["id"]},
        )
        # Written, but not readable without a user who may see it.
        visible = sa.text("SELECT count(*) FROM event_details WHERE event_id = :id")
        assert (await conn.execute(visible, {"id": event["id"]})).scalar_one() == 0


async def test_details_attach_only_to_own_or_actorless_events(owner_engine: AsyncEngine) -> None:
    """app_event_accepts_details(): user A cannot attach details to user B's event (or to a missing event), but can
    to A's own events and to events that name no actor."""
    user_a, user_b, chain = uuid7(), uuid7(), f"test:{uuid4().hex}"
    b_event, a_event = event_params(chain, user_b), event_params(chain, user_a)
    system_event = event_params(chain, None, actor_kind="system")
    details = "INSERT INTO event_details (event_id) VALUES (:id)"
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, b_event)  # written by B's own request earlier
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await act_as(conn, user_a)
        await conn.execute(INSERT_EVENT, a_event)
        await conn.execute(INSERT_EVENT, system_event)
        await expect_error(conn, details, "row-level security", {"id": b_event["id"]})
        await expect_error(conn, details, "row-level security", {"id": uuid7()})
        await conn.execute(sa.text(details), {"id": a_event["id"]})
        await conn.execute(sa.text(details), {"id": system_event["id"]})


async def test_events_cannot_name_another_user_as_actor(app_engine: AsyncEngine) -> None:
    """User events name the current user; system events name nobody; staff events name nobody or the current user.
    No kind of event may name another user."""
    actor, other, chain = uuid7(), uuid7(), f"test:{uuid4().hex}"
    refused = [("user", other), ("user", None), ("staff", other), ("system", other), ("system", actor)]
    accepted = [("user", actor), ("staff", actor), ("staff", None), ("system", None)]
    async with rolled_back(app_engine, actor) as conn:
        for kind, named in refused:
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="row-level security"):
                await conn.execute(INSERT_EVENT, event_params(chain, named, actor_kind=kind))
            await savepoint.rollback()
        for kind, named in accepted:
            await conn.execute(INSERT_EVENT, event_params(chain, named, actor_kind=kind))
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))  # read the whole chain back
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert [(row.actor_kind, row.actor_user_id) for row in chained] == accepted
    assert_linked_chain(chained)


# --- Schema v2 (revision 0002): protected columns, evidence triggers (AC-IP-2), the directory policy ----------------


async def test_schema_v2_protected_columns_and_tables_are_not_the_apps(app_engine: AsyncEngine) -> None:
    """What only definer functions, workers, staff or the owner may change: bridge_app is refused by its grants."""
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        for sql in (
            "SELECT subject_salt FROM users",
            "UPDATE users SET subject_salt = '\\x00'",
            "UPDATE organizations SET verified_domain = 'x.example'",
            "UPDATE organizations SET official_domains = '{}'",
            "UPDATE organizations SET delisted_at = now()",
            "UPDATE organizations SET suspended_at = now()",
            "UPDATE organizations SET e2_verified_at = now()",
            "UPDATE proposals SET moderation_state = 'clear'",
            "UPDATE proposals SET owner_id = owner_id",
            "UPDATE problems SET moderation_state = 'clear'",
            "UPDATE problems SET status = 'published'",
            "UPDATE org_claims SET otp_verified_at = now()",
            "UPDATE org_claims SET reviewed_by = NULL",
            "UPDATE kyc_reviews SET status = 'approved'",
            "UPDATE phone_verifications SET verified_at = now()",
            "UPDATE engagements SET state = 'CLOSED'",
            "UPDATE provenance_records SET status = 'timestamped'",
            "UPDATE attestations SET created_it = true",
            "UPDATE tags SET closed_at = NULL",
            "UPDATE org_claims SET otp_attempts = 0",
            "UPDATE org_claims SET otp_reissues = 0",
            "UPDATE org_claims SET otp_hash = NULL",
            "UPDATE org_claims SET otp_expires_at = now()",
            "UPDATE org_claims SET dns_verified_at = now()",
            "UPDATE org_claims SET dns_token = 'x'",
            "DELETE FROM nda_acceptances",
            "INSERT INTO provenance_keys (key_id, public_key) VALUES ('k', '\\x00')",
            "SELECT 1 FROM proposal_confidential",
            "SELECT 1 FROM proposal_confidential_embeddings",
            "SELECT 1 FROM signal_events",
            "SELECT 1 FROM chain_anchors",
        ):
            await expect_error(conn, sql, "permission denied")


async def test_subject_digests_come_from_the_database_and_the_orm_never_loads_the_salt(
    owner_engine: AsyncEngine,
) -> None:
    """Every user gets a random 32-byte salt from the database. bridge_app and provenance_worker get SHA-256(salt ||
    data) from app_subject_digest() (owner refs: data = the id's 16 bytes), never the salt; the ORM creates and loads
    users without selecting or returning it. (Who may compute whose digest: test_privileges.py.)"""
    from sqlalchemy.ext.asyncio import AsyncSession

    from bridge.auth.models import User

    async with rolled_back(owner_engine) as conn:
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        session = AsyncSession(bind=conn)
        user = User(email=f"{uuid4().hex}@example.test", display_name="Salted")
        session.add(user)
        await session.flush()  # INSERT ... RETURNING the server defaults, never subject_salt
        await act_as(conn, user.id)
        session.expunge_all()
        assert (await session.get(User, user.id)) is not None
        await session.close()
        digest = "SELECT app_subject_digest(:id, uuid_send(:id))"
        from_app = (await conn.execute(sa.text(digest), {"id": user.id})).scalar_one()
        await conn.execute(sa.text("SET LOCAL ROLE provenance_worker"))
        assert (await conn.execute(sa.text(digest), {"id": user.id})).scalar_one() == from_app
        unknown = "SELECT app_subject_digest(:id, '\\x00')"
        assert (await conn.execute(sa.text(unknown), {"id": uuid7()})).scalar_one() is None
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))
        salt = (
            await conn.execute(sa.text("SELECT subject_salt FROM users WHERE id = :id"), {"id": user.id})
        ).scalar_one()
        assert len(salt) == 32
        assert from_app == hashlib.sha256(salt + user.id.bytes).digest()  # bridge.provenance.manifest.owner_ref


# Columns bridge_app may never read (column-level SELECT on the rest of the table): OTP digests are compared in SQL.
# users.subject_salt: digests come from app_subject_digest(), the salt never leaves the database.
UNREADABLE_COLUMNS: dict[str, str] = {
    "org_claims": "otp_hash",
    "phone_verifications": "otp_hash",
    "users": "subject_salt",
    "llm_calls": "inputs",  # staff admin reads it through app_llm_call_inputs()
}


@pytest.mark.parametrize(("table", "column"), sorted(UNREADABLE_COLUMNS.items()))
async def test_bridge_app_reads_every_column_but_the_unreadable_one(
    owner_engine: AsyncEngine, table: str, column: str
) -> None:
    held = "SELECT has_column_privilege('bridge_app', CAST(:t AS text), CAST(:c AS text), 'SELECT')"
    assert await scalar(owner_engine, held, t=f"public.{table}", c=column) is False
    whole = "SELECT has_table_privilege('bridge_app', CAST(:t AS text), 'SELECT')"
    assert await scalar(owner_engine, whole, t=f"public.{table}") is False  # column-scoped, never table-wide
    readable = await rows(
        owner_engine,
        "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
        " WHERE has_column_privilege('bridge_app', CAST(:t AS text), c.name, 'SELECT')",
        columns=[c.name for c in TABLES[table].columns],
        t=f"public.{table}",
    )
    assert {row.name for row in readable} == {c.name for c in TABLES[table].columns} - {column}


async def test_bridge_app_inserts_every_users_column_but_demo_account(owner_engine: AsyncEngine) -> None:
    """D-37: whether an account is seeded demo data is the owner's (the seed); bridge_app inserts every other column of
    users (column-scoped since revision 0003), reads demo_account and never updates it."""
    held = "SELECT has_column_privilege('bridge_app', 'public.users', CAST(:c AS text), CAST(:p AS text))"
    assert await scalar(owner_engine, held, c="demo_account", p="INSERT") is False
    assert await scalar(owner_engine, held, c="demo_account", p="UPDATE") is False
    assert await scalar(owner_engine, held, c="demo_account", p="SELECT") is True
    whole = "SELECT has_table_privilege('bridge_app', 'public.users', 'INSERT')"
    assert await scalar(owner_engine, whole) is False  # column-scoped, never table-wide
    insertable = await rows(
        owner_engine,
        "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
        " WHERE has_column_privilege('bridge_app', 'public.users', c.name, 'INSERT')",
        columns=[c.name for c in TABLES["users"].columns],
    )
    assert {row.name for row in insertable} == {c.name for c in TABLES["users"].columns} - {"demo_account"}


# Revision 0005: columns bridge_app reads but neither inserts nor updates: the research columns only
# app_create_research_candidate() writes, and a scout run's start, the database's clock (never forward- or back-dated).
# Revision 0006: a note's time, the database's clock too, and its redaction (D-54), the owner's.
DEFINER_ONLY_COLUMNS: dict[str, set[str]] = {
    "problems": {"research_run_id", "named_orgs"},
    "problem_sources": {"excerpt_ref"},
    "agent_runs": {"started_at"},
    "engagement_notes": {"created_at", "redacted_at", "redacted_by"},  # D-54: a redaction is the owner's
    # Revision 0008: a message's time and redaction (as a note's), a shortlist entry's time.
    "engagement_messages": {"created_at", "redacted_at", "redacted_by"},
    "org_shortlist": {"added_at"},
}


@pytest.mark.parametrize(("table", "columns"), sorted(DEFINER_ONLY_COLUMNS.items()))
async def test_bridge_app_inserts_every_column_but_the_databases_ones(
    owner_engine: AsyncEngine, table: str, columns: set[str]
) -> None:
    held = "SELECT has_column_privilege('bridge_app', CAST(:t AS text), CAST(:c AS text), CAST(:p AS text))"
    for column in columns:
        assert await scalar(owner_engine, held, t=f"public.{table}", c=column, p="INSERT") is False
        assert await scalar(owner_engine, held, t=f"public.{table}", c=column, p="UPDATE") is False
        assert await scalar(owner_engine, held, t=f"public.{table}", c=column, p="SELECT") is True
    whole = "SELECT has_table_privilege('bridge_app', CAST(:t AS text), 'INSERT')"
    assert await scalar(owner_engine, whole, t=f"public.{table}") is False  # column-scoped, never table-wide
    insertable = await rows(
        owner_engine,
        "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
        " WHERE has_column_privilege('bridge_app', CAST(:t AS text), c.name, 'INSERT')",
        columns=[c.name for c in TABLES[table].columns],
        t=f"public.{table}",
    )
    assert {row.name for row in insertable} == {c.name for c in TABLES[table].columns} - columns


# Revision 0008: columns bridge_app inserts on the tables whose other columns it writes later (an upload's message and
# verdict, a search's last alert) or never (the database's times). The UPDATE side is APP_COLUMN_UPDATES.
V6_INSERT_EXCLUDED: dict[str, set[str]] = {
    # staged first and pending: sent and scanned by an UPDATE (the verdict is the API's: storage/scanner.py)
    "engagement_message_attachments": {"message_id", "av_status", "created_at"},
    "engagement_message_reads": set(),
    "saved_searches": {"last_alerted_at", "created_at"},  # the alert job's, the database's
}


@pytest.mark.parametrize(("table", "excluded"), sorted(V6_INSERT_EXCLUDED.items()))
async def test_schema_v6_insert_columns_are_exactly_the_apps(
    owner_engine: AsyncEngine, table: str, excluded: set[str]
) -> None:
    columns = [c.name for c in TABLES[table].columns]
    held = (
        "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
        " WHERE has_column_privilege('bridge_app', CAST(:t AS text), c.name, CAST(:p AS text))"
    )
    insertable = await rows(owner_engine, held, columns=columns, t=f"public.{table}", p="INSERT")
    assert {row.name for row in insertable} == set(columns) - excluded
    readable = await rows(owner_engine, held, columns=columns, t=f"public.{table}", p="SELECT")
    assert {row.name for row in readable} == set(columns)
    whole = "SELECT has_table_privilege('bridge_app', CAST(:t AS text), 'INSERT')"
    assert await scalar(owner_engine, whole, t=f"public.{table}") is False  # column-scoped, never table-wide


async def test_schema_v4_protected_columns_and_tables_are_not_the_apps(app_engine: AsyncEngine) -> None:
    """What only the definer functions, the database or the owner change in revision 0005: bridge_app is refused by
    its grants (payments are settled and linked only through app_settle_payment and
    app_activate_paid_subscription; runs are never deleted; keys, owners, creators and start times never change)."""
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        for sql in (
            "UPDATE payments SET status = 'succeeded'",
            "UPDATE payments SET subscription_id = NULL",
            "UPDATE payments SET settled_at = now()",
            "UPDATE payments SET amount_kes_minor = 1",
            "DELETE FROM payments",
            "UPDATE scout_agents SET org_id = org_id",
            "UPDATE scout_agents SET created_by = created_by",
            "DELETE FROM agent_runs",
            "UPDATE agent_runs SET started_at = now()",
            "UPDATE agent_runs SET scout_id = scout_id",
            "UPDATE agent_runs SET window_end = now()",
            "DELETE FROM agent_matches",
            "UPDATE agent_matches SET score = 100",
            "UPDATE agent_matches SET proposal_id = proposal_id",
            "UPDATE agent_matches SET rationale = 'x'",
            "DELETE FROM research_runs",
            "UPDATE research_runs SET started_by = started_by",
            "UPDATE research_runs SET niche_id = niche_id",
            "UPDATE problems SET research_run_id = NULL",
            "UPDATE problems SET named_orgs = '{}'",
            "INSERT INTO problems (id, source, title, statement, research_run_id) VALUES (uuid7(), 'developer', 't',"
            " 's', NULL)",
            "INSERT INTO problems (id, source, title, statement, named_orgs) VALUES (uuid7(), 'developer', 't', 's',"
            " '{}')",
            "INSERT INTO problem_sources (id, problem_id, url, retrieved_at, excerpt_ref) VALUES (uuid7(), uuid7(),"
            " 'https://example.test', now(), NULL)",
        ):
            await expect_error(conn, sql, "permission denied")


async def test_otp_digests_are_written_but_never_read_back(owner_engine: AsyncEngine) -> None:
    """The claimant and the phone owner write their code's digest and read their rows, through SQL and the ORM, but
    no statement of bridge_app returns the digest (offline brute force of a 6-digit code needs it)."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from bridge.directory.models import OrgClaim
    from bridge.profiles.models import PhoneVerification

    async with rolled_back(owner_engine) as conn:
        user, org, claim, code = uuid7(), uuid7(), uuid7(), uuid7()
        await add_user(conn, user)
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification) VALUES (:id, 'company',"
                " 'OTP Ltd', :slug, 'seed', 'unclaimed')"
            ),
            {"id": org, "slug": f"otp-{org.hex}"},
        )
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await act_as(conn, user)
        await conn.execute(
            sa.text(
                "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status, otp_hash,"
                " otp_expires_at) VALUES (:id, :org, :u, 'otp.example.test', 'info@otp.example.test', 'e1', 'otp_sent',"
                " :h, now() + interval '10 minutes')"
            ),
            {"id": claim, "org": org, "u": user, "h": ZERO_HASH},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash) VALUES (:id, :u, '+254712345678',"
                " :h)"
            ),
            {"id": code, "u": user, "h": ZERO_HASH},
        )
        for sql in (
            "SELECT otp_hash FROM org_claims",
            "SELECT * FROM org_claims",
            "SELECT otp_hash FROM phone_verifications",
            "SELECT * FROM phone_verifications",
            "SELECT id FROM org_claims WHERE otp_hash IS NOT NULL",
        ):
            await expect_error(conn, sql, "permission denied")
        session = AsyncSession(bind=conn)
        loaded_claim = await session.get(OrgClaim, claim)
        loaded_code = await session.get(PhoneVerification, code)
        assert loaded_claim is not None
        assert loaded_code is not None
        assert (loaded_claim.otp_attempts, loaded_code.attempts) == (0, 0)
        with pytest.raises(sa.exc.InvalidRequestError, match="raiseload"):
            _ = loaded_claim.otp_hash
        await session.close()


async def _registered_proposal(conn: AsyncConnection) -> tuple[UUID, UUID, UUID, UUID]:
    """As the owner: (owner, niche, proposal, registered version) of a fresh developer."""
    niche = uuid7()
    await conn.execute(
        sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Evidence')"),
        {"id": niche, "slug": f"evidence-{niche.hex}"},
    )
    owner = await w.add_user(conn, f"{uuid4().hex}@example.test", "Owner")
    problem = await w.add_problem(conn, owner, niche)
    proposal, version = await w.add_proposal(conn, owner, niche, problem)
    return owner, niche, proposal, version


async def test_registered_versions_refuse_update_and_delete(owner_engine: AsyncEngine) -> None:
    """AC-IP-2 (manifest half): the trigger holds for every role, the owner included; only the empty registration
    hashes may be filled, once. Drafts stay editable, and a version is inserted as a draft and registered only with a
    linked problem. registered_at and owner_handle are the database's: values sent at registration are replaced by
    now() and the owner's developer handle (a developer without a profile cannot register), and neither they nor a
    registration hash can be set on a draft."""
    h1, h2 = hashlib.sha256(b"manifest-1").digest(), hashlib.sha256(b"manifest-2").digest()
    async with rolled_back(owner_engine) as conn:
        owner, niche, proposal, version = await _registered_proposal(conn)
        by_id = {"id": version}
        for assignment in (
            "title = 'Edited'",
            "summary = 'Edited'",
            "status = 'draft'",
            "cert_id = 'another'",
            "registered_at = now() - interval '1 day'",  # now() itself is the value it was registered with
            "owner_handle = 'someone-else'",
        ):
            await expect_error(conn, f"UPDATE proposal_versions SET {assignment} WHERE id = :id", "immutable", by_id)
        await expect_error(conn, "DELETE FROM proposal_versions WHERE id = :id", "never deleted", by_id)
        await expect_error(conn, "DELETE FROM proposals WHERE id = :id", "never deleted", {"id": proposal})
        fill = "UPDATE proposal_versions SET content_hash = :h, manifest_version = 'm1' WHERE id = :id"
        await conn.execute(sa.text(fill), {"id": version, "h": h1})
        await expect_error(conn, fill, "immutable", {"id": version, "h": h2})
        await expect_error(conn, "UPDATE proposal_versions SET content_hash = NULL WHERE id = :id", "immutable", by_id)
        await expect_error(conn, "TRUNCATE proposal_versions CASCADE", "append-only evidence")

        problem = await w.add_problem(conn, owner, niche)
        draft, draft_version = await w.add_proposal(conn, owner, niche, problem, registered=False)
        await conn.execute(
            sa.text("UPDATE proposal_versions SET title = 'Draft edit' WHERE id = :id"), {"id": draft_version}
        )
        second = uuid7()
        await conn.execute(sa.text(NEW_VERSION), {"id": second, "p": draft, "n": 2, "niche": niche})
        await expect_error(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :c, registered_at = now() WHERE id = :id",
            "at least one linked problem",
            {"id": second, "c": uuid4().hex[:16]},
        )
        await expect_error(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no, status) VALUES (:id, :p, 3, 'registered')",
            "inserted as a draft",
            {"id": uuid7(), "p": draft},
        )
        for assignment in (
            "registered_at = now()",
            "owner_handle = 'someone-else'",
            "content_hash = :h",
            "prev_version_hash = :h",
            "manifest_version = 'm'",
        ):
            await expect_error(
                conn,
                f"UPDATE proposal_versions SET {assignment} WHERE id = :id",
                "owner_handle are set at registration|filled after registration",
                {"id": second, "h": h1},
            )
        for column, value in (
            ("registered_at", "now()"),
            ("owner_handle", "'someone-else'"),
            ("content_hash", ":h"),
            ("manifest_version", "'m'"),
        ):
            await expect_error(
                conn,
                f"INSERT INTO proposal_versions (id, proposal_id, version_no, {column}) VALUES (:id, :p, 3, {value})",
                "set at registration",
                {"id": uuid7(), "p": draft, "h": h1},
            )
        await conn.execute(sa.text("DELETE FROM proposal_versions WHERE id = :id"), {"id": second})  # drafts may go
        # Registering sets registered_at to the transaction's now() and owner_handle to the owner's developer handle,
        # whatever the writer sends.
        register = (
            "UPDATE proposal_versions SET status = 'registered', cert_id = :c, registered_at = :t,"
            " owner_handle = 'someone-else' WHERE id = :id"
        )
        registration = {"id": draft_version, "c": uuid4().hex[:16], "t": datetime(2001, 1, 1, tzinfo=UTC)}
        handle = "DELETE FROM developer_profiles WHERE user_id = :u RETURNING handle"
        owner_handle = (await conn.execute(sa.text(handle), {"u": owner})).scalar_one()
        await expect_error(conn, register, "needs the owner's developer profile", registration)
        await conn.execute(
            sa.text("INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)"), {"u": owner, "h": owner_handle}
        )
        await conn.execute(sa.text(register), registration)
        stamped = sa.text("SELECT registered_at = now(), owner_handle::text FROM proposal_versions WHERE id = :id")
        assert tuple((await conn.execute(stamped, {"id": draft_version})).one()) == (True, owner_handle)


NEW_VERSION = (
    "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask, problem_statement,"
    " summary) VALUES (:id, :p, :n, 'T', :niche, 'idea', 'pilot', 'P', 'S')"
)


async def test_proposal_version_pointers_follow_the_version_status(owner_engine: AsyncEngine) -> None:
    """current_version_id is always a registered version of the proposal and draft_version_id a draft one (trigger,
    for every role; the composite foreign keys keep both inside the proposal)."""
    async with rolled_back(owner_engine) as conn:
        owner, niche, proposal, registered = await _registered_proposal(conn)
        problem = await w.add_problem(conn, owner, niche)
        _other, other_draft = await w.add_proposal(conn, owner, niche, problem, registered=False)
        draft = uuid7()
        await conn.execute(sa.text(NEW_VERSION), {"id": draft, "p": proposal, "n": 2, "niche": niche})
        point = "UPDATE proposals SET {column} = :v WHERE id = :id"
        current, pending = point.format(column="current_version_id"), point.format(column="draft_version_id")
        await expect_error(conn, current, "registered version of the proposal", {"id": proposal, "v": draft})
        await expect_error(conn, pending, "draft version of the proposal", {"id": proposal, "v": registered})
        # Another proposal's version: refused by the trigger (before the composite foreign key would refuse it).
        await expect_error(conn, current, "registered version of the proposal", {"id": proposal, "v": other_draft})
        await conn.execute(sa.text(pending), {"id": proposal, "v": draft})
        # Register the draft first, then point current_version_id at it (the app's order).
        await conn.execute(
            sa.text("INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:v, :p)"),
            {"v": draft, "p": problem},
        )
        await conn.execute(
            sa.text(
                "UPDATE proposal_versions SET status = 'registered', cert_id = :c, registered_at = now() WHERE id = :v"
            ),
            {"v": draft, "c": uuid4().hex[:16]},
        )
        await conn.execute(
            sa.text("UPDATE proposals SET current_version_id = :v, draft_version_id = NULL WHERE id = :id"),
            {"id": proposal, "v": draft},
        )
        # An unchanged pointer is not re-checked: a stale draft_version_id never blocks unrelated edits.
        third = uuid7()
        await conn.execute(sa.text(NEW_VERSION), {"id": third, "p": proposal, "n": 3, "niche": niche})
        await conn.execute(sa.text(pending), {"id": proposal, "v": third})
        await conn.execute(
            sa.text("INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:v, :p)"),
            {"v": third, "p": problem},
        )
        await conn.execute(
            sa.text(
                "UPDATE proposal_versions SET status = 'registered', cert_id = :c, registered_at = now() WHERE id = :v"
            ),
            {"v": third, "c": uuid4().hex[:16]},
        )
        await conn.execute(sa.text("UPDATE proposals SET title = 'Renamed' WHERE id = :id"), {"id": proposal})
        await expect_error(conn, pending, "draft version of the proposal", {"id": proposal, "v": registered})


async def test_tier2_of_a_registered_version_is_frozen_except_the_manifest(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        owner, niche, _proposal, version = await _registered_proposal(conn)
        by_id = {"id": version}
        await expect_error(
            conn, "UPDATE proposal_confidential SET ciphertext = '\\x09' WHERE version_id = :id", "immutable", by_id
        )
        await expect_error(conn, "DELETE FROM proposal_confidential WHERE version_id = :id", "never deleted", by_id)
        await expect_error(
            conn,
            "UPDATE proposal_confidential SET manifest_ciphertext = '\\x0a' WHERE version_id = :id",
            "manifest_pair",
            by_id,
        )
        fill = "UPDATE proposal_confidential SET manifest_ciphertext = :m, manifest_nonce = :n WHERE version_id = :id"
        await conn.execute(sa.text(fill), {"id": version, "m": b"\x0a", "n": b"\x0b"})
        await expect_error(conn, fill, "immutable", {"id": version, "m": b"\x0c", "n": b"\x0d"})
        # A draft's Tier 2 stays editable; Tier 2 always belongs to the version's owner and proposal.
        problem = await w.add_problem(conn, owner, niche)
        _draft, draft_version = await w.add_proposal(conn, owner, niche, problem, registered=False)
        await conn.execute(
            sa.text("UPDATE proposal_confidential SET ciphertext = '\\x09' WHERE version_id = :id"),
            {"id": draft_version},
        )
        stranger = await w.add_user(conn, f"{uuid4().hex}@example.test", "Stranger")
        await expect_error(
            conn,
            "UPDATE proposal_confidential SET owner_id = :u WHERE version_id = :id",
            "never change",
            {"id": draft_version, "u": stranger},
        )


async def test_attachments_of_a_registered_version_change_only_their_scan_state(owner_engine: AsyncEngine) -> None:
    """A draft's attachments stay editable; once the version is registered the owner (as bridge_app) and every other
    role may change only av_status, rerendered and updated_at, and nobody deletes the attachment."""
    h1, h2 = hashlib.sha256(b"attachment-1").digest(), hashlib.sha256(b"attachment-2").digest()
    async with rolled_back(owner_engine) as conn:
        owner, niche, _proposal, _registered = await _registered_proposal(conn)
        problem = await w.add_problem(conn, owner, niche)
        draft, version = await w.add_proposal(conn, owner, niche, problem, registered=False)
        attachment = uuid7()
        by_id = {"id": attachment, "h": h2}
        await conn.execute(
            sa.text(
                "INSERT INTO proposal_attachments (id, owner_id, proposal_id, version_id, content_type, sha256,"
                " size_bytes) VALUES (:id, :owner, :p, :v, 'application/pdf', :h, 100)"
            ),
            {"id": attachment, "owner": owner, "p": draft, "v": version, "h": h1},
        )
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(owner)})
        await conn.execute(sa.text("UPDATE proposal_attachments SET sha256 = :h WHERE id = :id"), by_id)  # a draft's
        await conn.execute(
            sa.text("UPDATE proposal_versions SET status = 'registered', cert_id = :c WHERE id = :v"),
            {"v": version, "c": uuid4().hex[:16]},
        )
        for assignment in ("sha256 = :h", "size_bytes = 200", "sha256 = NULL"):
            await expect_error(
                conn,
                f"UPDATE proposal_attachments SET {assignment} WHERE id = :id",
                "changes only its scan state",
                {"id": attachment, "h": h1},
            )
        scanned = await conn.execute(
            sa.text("UPDATE proposal_attachments SET av_status = 'clean', rerendered = true WHERE id = :id"), by_id
        )
        assert scanned.rowcount == 1
        removed = await conn.execute(sa.text("DELETE FROM proposal_attachments WHERE id = :id"), by_id)
        assert removed.rowcount == 0  # the DELETE policy covers drafts only
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))  # the trigger holds for every role
        for sql in ("UPDATE proposal_attachments SET content_type = 'text/plain' WHERE id = :id",):
            await expect_error(conn, sql, "changes only its scan state", by_id)
        await expect_error(conn, "DELETE FROM proposal_attachments WHERE id = :id", "never deleted", by_id)


# A registration record of a version, with the version's own cert_id (fk_provenance_records_version_cert).
RECORD_OF_VERSION = (
    "INSERT INTO provenance_records (id, version_id, cert_id, content_hash)"
    " SELECT :id, v.id, v.cert_id, :h FROM proposal_versions v WHERE v.id = :v"
)


async def test_a_record_carries_its_versions_cert_id_and_content_hash(owner_engine: AsyncEngine) -> None:
    """A registration record is the record of its version, for every role: its cert_id is the version's (a composite
    foreign key), and its content_hash equals the version's once both are set, whichever is written first (the job
    inserts the record, then fills the version's hashes)."""
    h1, h2 = hashlib.sha256(b"manifest-1").digest(), hashlib.sha256(b"manifest-2").digest()
    async with rolled_back(owner_engine) as conn:
        _owner, _niche, _proposal, first = await _registered_proposal(conn)
        _other, _niche2, _proposal2, second = await _registered_proposal(conn)
        cert = sa.text("SELECT cert_id FROM proposal_versions WHERE id = :v")
        certs = {v: (await conn.execute(cert, {"v": v})).scalar_one() for v in (first, second)}
        record = "INSERT INTO provenance_records (id, version_id, cert_id, content_hash) VALUES (:id, :v, :c, :h)"
        fill = "UPDATE proposal_versions SET content_hash = :h WHERE id = :v"
        another_cert = {"id": uuid7(), "v": first, "c": certs[second], "h": h1}
        await expect_error(conn, record, "fk_provenance_records_version_cert", another_cert)
        await conn.execute(sa.text(record), {"id": uuid7(), "v": first, "c": certs[first], "h": h1})  # the job's order
        await expect_error(conn, fill, "content hash of its provenance record", {"v": first, "h": h2})
        await conn.execute(sa.text(fill), {"v": first, "h": h1})
        await conn.execute(sa.text(fill), {"v": second, "h": h1})  # the version's hash first
        mismatch = {"id": uuid7(), "v": second, "c": certs[second], "h": h2}
        await expect_error(conn, record, "content hash of its version", mismatch)
        await conn.execute(sa.text(record), {"id": uuid7(), "v": second, "c": certs[second], "h": h1})


async def test_upload_matching_finds_a_record_by_content_hash_through_an_index(owner_engine: AsyncEngine) -> None:
    """POST /api/verify without a cert id matches an uploaded file's SHA-256 against every record: the lookup uses
    ix_provenance_records_content_hash rather than scanning the table."""
    async with rolled_back(owner_engine) as conn:
        await conn.execute(sa.text("SET LOCAL enable_seqscan = off"))  # any usable index is taken over a scan
        plan = await conn.execute(
            sa.text("EXPLAIN (COSTS OFF) SELECT cert_id FROM provenance_records WHERE content_hash = :h"),
            {"h": ZERO_HASH},
        )
        assert "ix_provenance_records_content_hash" in " ".join(plan.scalars())


async def test_provenance_records_only_fill_empty_columns_and_move_forward(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        owner, _niche, _proposal, version = await _registered_proposal(conn)
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(owner)})  # the job's owner
        key_id, record = f"test-{uuid4().hex[:8]}", uuid7()
        await conn.execute(
            sa.text("INSERT INTO provenance_keys (key_id, public_key) VALUES (:k, :pk)"), {"k": key_id, "pk": bytes(32)}
        )
        await conn.execute(sa.text(RECORD_OF_VERSION), {"id": record, "v": version, "h": ZERO_HASH})
        by_id = {"id": record}
        sign = "UPDATE provenance_records SET signature = '\\x01', key_id = :k, status = 'signed' WHERE id = :id"
        await conn.execute(sa.text(sign), {"id": record, "k": key_id})
        refused = "only empty signature"
        await expect_error(conn, "UPDATE provenance_records SET status = 'hashed' WHERE id = :id", refused, by_id)
        await conn.execute(sa.text("SET LOCAL ROLE provenance_worker"))  # the worker that fills the TSA columns
        await conn.execute(
            sa.text(
                "UPDATE provenance_records SET tsa_token = '\\x02', tsa_time = now(), tsa_serial = '42',"
                " tsa_url = 'https://tsa.example.test', status = 'timestamped' WHERE id = :id"
            ),
            by_id,
        )
        await expect_error(
            conn, "UPDATE provenance_records SET content_hash = '\\x00' WHERE id = :id", "permission denied", by_id
        )
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))
        for assignment in ("tsa_token = '\\x03'", "signature = '\\x04'", "content_hash = '\\x05'", "cert_id = 'x'"):
            await expect_error(conn, f"UPDATE provenance_records SET {assignment} WHERE id = :id", refused, by_id)
        await expect_error(conn, "DELETE FROM provenance_records WHERE id = :id", "never deleted", by_id)
        await expect_error(conn, "TRUNCATE provenance_records", "append-only evidence")


async def test_append_only_evidence_refuses_update_and_delete_even_for_the_owner(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        owner, _niche, _proposal, version = await _registered_proposal(conn)
        await conn.execute(
            sa.text(
                "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
                " no_third_party_confidential, text_version, text_sha256)"
                " VALUES (:id, :u, :v, true, true, true, 'v1', :h)"
            ),
            {"id": uuid7(), "u": owner, "v": version, "h": ZERO_HASH},
        )
        chain = f"test:{uuid4().hex}"  # an anchor names an existing audit event (chain_anchors_guard)
        await conn.execute(
            sa.text("INSERT INTO audit_events (id, chain_id, actor_kind, action) VALUES (:id, :c, 'system', 'test.x')"),
            {"id": uuid7(), "c": chain},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO chain_anchors (id, chain_id, seq, event_hash, tsa_token, tsa_time, tsa_serial)"
                " SELECT :id, chain_id, seq, event_hash, '\\x01', now(), '1' FROM audit_events WHERE chain_id = :c"
            ),
            {"id": uuid7(), "c": chain},
        )
        for table in ("attestations", "chain_anchors"):
            await expect_error(conn, f"UPDATE {table} SET id = id", "append-only evidence")
            await expect_error(conn, f"DELETE FROM {table}", "append-only evidence")


async def test_evidence_times_are_the_databases(owner_engine: AsyncEngine) -> None:
    """When an attestation was made, the Master Enterprise Terms or an NDA accepted and a Tier-2 view started is
    evidence: the database sets it to now() on insert, whatever the writer sends (a backdated value is replaced), for
    every role, the owner included."""
    backdated = datetime.now(UTC) - timedelta(days=30)
    async with rolled_back(owner_engine) as conn:
        owner, _niche, proposal, version = await _registered_proposal(conn)
        org, attestation, terms, nda, view = uuid7(), uuid7(), uuid7(), uuid7(), uuid7()
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'company', 'Evidence Ltd',"
                " :slug, 'seed')"
            ),
            {"id": org, "slug": f"evidence-{org.hex}"},
        )
        met_template, nda_template = await w.add_templates(conn, uuid4().hex[:12])
        params = {"t": backdated, "u": owner, "org": org, "p": proposal, "v": version, "h": ZERO_HASH}
        for statement, row in (
            (
                "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
                " no_third_party_confidential, text_version, text_sha256, created_at)"
                " VALUES (:id, :u, :v, true, true, true, 'v1', :h, :t)",
                {"id": attestation},
            ),
            (
                "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256, accepted_at)"
                " SELECT :id, :org, :u, id, sha256, :t FROM legal_templates WHERE id = :template",
                {"id": terms, "template": met_template},
            ),
            (
                "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
                " logging_notice_version, accepted_at) SELECT :id, :u, :org, :p, id, sha256, 'v1', :t"
                " FROM nda_templates WHERE id = :template",
                {"id": nda, "template": nda_template},
            ),
            (
                "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id,"
                " nda_acceptance_id, render_kind, fingerprint_seed, started_at)"
                " VALUES (:id, :p, :v, :u, :u, :org, :nda, 'html', :h, :t)",
                {"id": view, "nda": nda},
            ),
        ):
            await conn.execute(sa.text(statement), params | row)
        for table, column, row_id in (
            ("attestations", "created_at", attestation),
            ("legal_acceptances", "accepted_at", terms),
            ("nda_acceptances", "accepted_at", nda),
            ("document_views", "started_at", view),
        ):
            stamped = sa.text(f"SELECT {column} = now() FROM {table} WHERE id = :id")
            assert (await conn.execute(stamped, {"id": row_id})).scalar_one() is True, f"{table}.{column} was backdated"


# pg_trigger.tgtype bits: see AUDIT_TRIGGERS.
V2_APPEND_ONLY = ("attestations", "nda_acceptances", "legal_acceptances", "chain_anchors", "transparency_roots")
V2_TRIGGERS = {
    ("proposal_versions", "proposal_versions_guard"): (
        "proposal_versions_guard",
        ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE,
    ),
    ("proposal_confidential", "proposal_confidential_guard"): (
        "proposal_confidential_guard",
        ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE,
    ),
    ("provenance_records", "provenance_records_guard"): (
        "provenance_records_guard",
        ROW | BEFORE | ON_DELETE | ON_UPDATE,
    ),
    ("proposal_attachments", "proposal_attachments_guard"): (
        "proposal_attachments_guard",
        ROW | BEFORE | ON_DELETE | ON_UPDATE,
    ),
    ("tags", "tags_guard"): ("tags_guard", ROW | BEFORE | ON_UPDATE),
    ("proposals", "proposals_guard"): ("proposals_guard", ROW | BEFORE | ON_INSERT | ON_UPDATE),
    ("org_claims", "org_claims_guard"): ("org_claims_guard", ROW | BEFORE | ON_INSERT),
    ("org_claims", "org_claims_dns_guard"): ("org_claims_dns_guard", ROW | BEFORE | ON_UPDATE),
    ("org_claims", "org_claims_status_guard"): ("org_claims_status_guard", ROW | BEFORE | ON_UPDATE),
    # Round 6: an AFTER trigger on the 0001 table relabels the organisation's open claims on every roster change.
    ("memberships", "memberships_claims_relabel"): ("memberships_claims_relabel", ROW | ON_INSERT | ON_UPDATE),
    ("llm_calls", "llm_calls_batch_guard"): ("llm_calls_batch_guard", ROW | BEFORE | ON_INSERT),
    ("phone_verifications", "phone_verifications_guard"): ("phone_verifications_guard", ROW | BEFORE | ON_INSERT),
    ("chain_anchors", "chain_anchors_guard"): ("chain_anchors_guard", ROW | BEFORE | ON_INSERT),
    ("provenance_records", "provenance_records_hash_guard"): (
        "provenance_records_hash_guard",
        ROW | BEFORE | ON_INSERT,
    ),
    ("transparency_roots", "transparency_roots_guard"): ("transparency_roots_guard", ROW | BEFORE | ON_INSERT),
    **{
        (t, f"{t}_evidence_time"): ("evidence_time_guard", ROW | BEFORE | ON_INSERT)
        for t in ("attestations", "legal_acceptances", "nda_acceptances", "document_views")
    },
    **{(t, f"{t}_no_update_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE | ON_UPDATE) for t in V2_APPEND_ONLY},
    **{
        (t, f"{t}_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE)
        for t in (*V2_APPEND_ONLY, "proposal_versions", "proposal_confidential", "provenance_records")
    },
}


# Revision 0003: the chain and its projection, the tracker guards, and the append-only tracker tables.
V3_APPEND_ONLY = ("engagement_events", "engagement_endorsements", "signatures")
V3_TRACKER_TABLES = (*V3_APPEND_ONLY, "agreements", "milestones", "payment_records")
V3_TRIGGERS = {
    ("engagements", "engagements_guard"): ("engagements_guard", ROW | BEFORE | ON_INSERT | ON_UPDATE),
    ("engagements", "engagements_genesis"): ("engagements_genesis", ROW | ON_INSERT),
    # After RLS: checks that read other users (the roster, TOTP enrolment).
    ("engagements", "engagements_members"): ("engagements_members", ROW | ON_INSERT | ON_UPDATE),
    ("engagement_endorsements", "engagement_endorsements_totp"): ("engagement_endorsements_totp", ROW | ON_INSERT),
    ("signatures", "signatures_totp"): ("signatures_totp", ROW | ON_INSERT),
    ("engagement_events", "engagement_events_chain"): ("engagement_events_chain", ROW | BEFORE | ON_INSERT),
    ("engagement_events", "engagement_events_project"): ("engagement_events_project", ROW | ON_INSERT),
    ("engagement_endorsements", "engagement_endorsements_guard"): (
        "engagement_endorsements_guard",
        ROW | BEFORE | ON_INSERT,
    ),
    ("agreements", "agreements_guard"): ("agreements_guard", ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE),
    ("milestones", "milestones_guard"): ("milestones_guard", ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE),
    ("signatures", "signatures_guard"): ("signatures_guard", ROW | BEFORE | ON_INSERT),
    ("payment_records", "payment_records_guard"): ("payment_records_guard", ROW | BEFORE | ON_INSERT | ON_UPDATE),
    ("payment_records", "payment_records_no_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE),
    **{(t, f"{t}_no_update_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE | ON_UPDATE) for t in V3_APPEND_ONLY},
    # Fires first on INSERT (name order): no definer trigger reads or locks an engagement the caller cannot see.
    **{
        (t, f"{t}_0_visible"): ("tracker_engagement_visible", ROW | BEFORE | ON_INSERT)
        for t in (*V3_APPEND_ONLY, "agreements", "milestones", "payment_records")
    },
    **{
        (t, f"{t}_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE)
        for t in (*V3_APPEND_ONLY, "agreements", "milestones", "payment_records")
    },
}


# Revision 0005: the payment guard, the research publication backstop and the scout recipients check.
V5_TRIGGERS = {
    ("payments", "payments_guard"): ("payments_guard", ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE),
    ("payments", "payments_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE),
    ("problems", "problems_research_guard"): ("problems_research_guard", ROW | BEFORE | ON_INSERT | ON_UPDATE),
    # After RLS: reads the organisation's roster.
    ("scout_agents", "scout_agents_recipients"): ("scout_agents_recipients", ROW | ON_INSERT | ON_UPDATE),
    ("agent_matches", "agent_matches_feedback_guard"): ("agent_matches_feedback_guard", ROW | BEFORE | ON_UPDATE),
    ("research_runs", "research_runs_guard"): ("research_runs_guard", ROW | BEFORE | ON_UPDATE),
    # Fires first on INSERT (name order): no unique or foreign key error reveals another organisation's scout.
    **{(t, f"{t}_0_visible"): ("scout_row_visible", ROW | BEFORE | ON_INSERT) for t in ("agent_runs", "agent_matches")},
}


# Revision 0006: the notes are a tracker table (the visibility check first) and append-only for every role; the
# Brief status and text guards.
V6_TRIGGERS = {
    ("engagement_notes", "engagement_notes_0_visible"): ("tracker_engagement_visible", ROW | BEFORE | ON_INSERT),
    # Second on INSERT (name order): a note only while its event is the latest, under the engagement's row lock.
    ("engagement_notes", "engagement_notes_1_latest_event"): (
        "engagement_notes_latest_event",
        ROW | BEFORE | ON_INSERT,
    ),
    ("engagement_notes", "engagement_notes_no_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE),
    # D-54: an UPDATE only as the owner's one redaction of the body.
    ("engagement_notes", "engagement_notes_redaction_guard"): (
        "engagement_notes_redaction_guard",
        ROW | BEFORE | ON_UPDATE,
    ),
    ("engagement_notes", "engagement_notes_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE),
    # After RLS: a Brief is published only with its problem, and closed only once published.
    ("problem_briefs", "problem_briefs_status_guard"): ("problem_briefs_status_guard", ROW | ON_INSERT | ON_UPDATE),
    # UPDATE OF title, statement, affected_group: a published Brief keeps its moderated text.
    ("problems", "problems_brief_text_guard"): ("problems_brief_text_guard", ROW | BEFORE | ON_UPDATE),
}


# Revision 0008: the thread's tables follow the tracker's pattern (the visibility check first on INSERT, then the stage
# gate); messages are append-only for every role (an UPDATE only as the owner's redaction, D-54); a sent attachment
# never changes; the caps count after the rows are in (after RLS).
V8_TRIGGERS = {
    **{
        (t, f"{t}_0_visible"): ("tracker_engagement_visible", ROW | BEFORE | ON_INSERT)
        for t in ("engagement_messages", "engagement_message_attachments", "engagement_message_reads")
    },
    **{
        (t, f"{t}_1_open"): ("engagement_thread_open", ROW | BEFORE | ON_INSERT)
        for t in ("engagement_messages", "engagement_message_attachments")
    },
    ("engagement_messages", "engagement_messages_no_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE),
    ("engagement_messages", "engagement_messages_redaction_guard"): (
        "engagement_messages_redaction_guard",
        ROW | BEFORE | ON_UPDATE,
    ),
    **{
        (t, f"{t}_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE)
        for t in ("engagement_messages", "engagement_message_attachments")
    },
    ("engagement_message_attachments", "engagement_message_attachments_guard"): (
        "engagement_message_attachments_guard",
        ROW | BEFORE | ON_UPDATE | ON_DELETE,
    ),
    # AFTER INSERT OR UPDATE OF message_id (the column list is not in tgtype).
    ("engagement_message_attachments", "engagement_message_attachments_cap"): (
        "engagement_message_attachments_cap",
        ROW | ON_INSERT | ON_UPDATE,
    ),
    ("saved_searches", "saved_searches_cap"): ("saved_searches_cap", ROW | ON_INSERT),
}
V8_THREAD_TABLES = ("engagement_messages", "engagement_message_attachments", "engagement_message_reads")

# Revision 0009: a set changes once (its decision); a question joins a draft and changes only by a pull or restore; an
# attempt is scored by the database at insert and changes only by its rescore; a flag never changes.
V9_TRIGGERS = {
    ("quiz_sets", "quiz_sets_guard"): ("quiz_sets_guard", ROW | BEFORE | ON_UPDATE),
    ("quiz_questions", "quiz_questions_guard"): ("quiz_questions_guard", ROW | BEFORE | ON_INSERT | ON_UPDATE),
    ("quiz_attempts", "quiz_attempts_score"): ("quiz_attempts_score", ROW | BEFORE | ON_INSERT),
    ("quiz_attempts", "quiz_attempts_guard"): ("quiz_attempts_guard", ROW | BEFORE | ON_UPDATE),
    ("quiz_flags", "quiz_flags_no_update"): ("block_mutation", ROW | BEFORE | ON_UPDATE),
}


async def test_a_published_briefs_text_changes_only_with_a_return_to_review(owner_engine: AsyncEngine) -> None:
    """Revision 0006 (REQ-DIR-05, the P19-B security review): problems_brief_text_guard keeps the moderated text of a
    published org_brief problem, for every role. Its organisation's editor (bridge_app) is refused with SQLSTATE 55000
    and holds no UPDATE on status to return it to review; the owner's same UPDATE with status = 'pending_review'
    passes. Unchanged text, the other columns, a Brief awaiting review and a developer's own problem stay editable."""
    async with rolled_back(owner_engine) as conn:
        p = await tracker.parties(conn)
        niche = uuid7()
        await conn.execute(
            sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Briefs')"),
            {"id": niche, "slug": niche.hex},
        )
        published = await w.add_problem(conn, p.reviewer, niche, org_id=p.org)
        pending = await w.add_problem(conn, p.reviewer, niche, org_id=p.org, status="pending_review")
        own = await w.add_problem(conn, p.developer, niche)
        by_id = {"id": published}
        await tracker.act(conn, p.reviewer, p.org)
        for column in ("title", "statement", "affected_group"):
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="moderated text of a published Brief") as refused:
                await conn.execute(sa.text(f"UPDATE problems SET {column} = 'Changed' WHERE id = :id"), by_id)
            await savepoint.rollback()
            assert getattr(refused.value.orig, "sqlstate", None) == "55000", column
        back_to_review = "UPDATE problems SET title = 'Changed', status = 'pending_review' WHERE id = :id"
        await expect_error(conn, back_to_review, "permission denied", by_id)  # status is a moderation decision
        unchanged = "UPDATE problems SET title = title, statement = statement, niche_id = niche_id WHERE id = :id"
        assert (await conn.execute(sa.text(unchanged), by_id)).rowcount == 1
        edit = "UPDATE problems SET title = 'Edited', affected_group = 'Farmers' WHERE id = :id"
        assert (await conn.execute(sa.text(edit), {"id": pending})).rowcount == 1
        await tracker.act(conn, p.developer)
        assert (await conn.execute(sa.text(edit), {"id": own})).rowcount == 1
        await tracker.as_owner(conn)  # every role: the owner too, unless it returns the Brief to review
        await expect_error(conn, "UPDATE problems SET title = 'Changed' WHERE id = :id", "moderated text", by_id)
        returned = await conn.execute(sa.text(back_to_review + " RETURNING CAST(status AS text)"), by_id)
        assert returned.scalar_one() == "pending_review"


async def test_every_trigger_is_installed_and_enabled(owner_engine: AsyncEngine) -> None:
    """The complete set of triggers on Bridge tables (Procrastinate's own are left to its schema)."""
    found = await rows(
        owner_engine,
        "SELECT c.relname AS table_name, t.tgname, t.tgfoid::regproc::text AS function, t.tgtype, t.tgenabled"
        " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal"
        " AND c.relnamespace = 'public'::regnamespace AND c.relname NOT LIKE 'procrastinate%'",
    )
    expected = AUDIT_TRIGGERS | V2_TRIGGERS | V3_TRIGGERS | V5_TRIGGERS | V6_TRIGGERS | V8_TRIGGERS | V9_TRIGGERS
    assert {(row.table_name, row.tgname): (row.function, row.tgtype) for row in found} == expected
    assert {row.tgenabled for row in found} == {"O"}


async def test_listed_organisations_are_readable_by_every_signed_in_user(owner_engine: AsyncEngine) -> None:
    """The directory: unclaimed, E1 and E2 organisations that are not delisted, and their niches, are readable by
    every signed-in user; pending self-signup organisations of others, rejected and delisted ones are not."""
    async with rolled_back(owner_engine) as conn:
        viewer, creator = uuid7(), uuid7()
        await add_user(conn, viewer)
        await add_user(conn, creator)
        niche = uuid7()
        await conn.execute(
            sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Directory')"),
            {"id": niche, "slug": f"dir-{niche.hex}"},
        )
        orgs: dict[str, UUID] = {}
        for name, verification, source, delisted in (
            ("unclaimed", "unclaimed", "seed", False),
            ("e1", "e1", "seed", False),
            ("e2", "e2", "self_signup", False),
            ("pending", "pending", "self_signup", False),
            ("rejected", "rejected", "self_signup", False),
            ("delisted", "unclaimed", "seed", True),
        ):
            orgs[name] = uuid7()
            await conn.execute(
                sa.text(
                    "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, created_by,"
                    " delisted_at) VALUES (:id, 'company', :name, :slug, CAST(:source AS org_source),"
                    " CAST(:verification AS org_verification), :creator, CASE WHEN :delisted THEN now() END)"
                ),
                {
                    "id": orgs[name],
                    "name": name,
                    "slug": f"{name}-{uuid4().hex}",
                    "source": source,
                    "verification": verification,
                    "creator": creator,
                    "delisted": delisted,
                },
            )
            await conn.execute(
                sa.text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"),
                {"org": orgs[name], "niche": niche},
            )
        listed = {orgs["unclaimed"], orgs["e1"], orgs["e2"]}
        ids = {"ids": list(orgs.values())}
        visible_orgs = sa.text("SELECT id FROM organizations WHERE id = ANY (:ids)")
        visible_niches = sa.text("SELECT org_id FROM org_niches WHERE org_id = ANY (:ids)")
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        assert set((await conn.execute(visible_orgs, ids)).scalars()) == set()  # not signed in: nothing
        await act_as(conn, viewer)
        assert set((await conn.execute(visible_orgs, ids)).scalars()) == listed
        assert set((await conn.execute(visible_niches, ids)).scalars()) == listed
        edit = sa.text("UPDATE organizations SET website = 'https://evil.example' WHERE id = ANY (:ids)")
        assert (await conn.execute(edit, ids)).rowcount == 0  # readable is not writable


# --- Procrastinate ------------------------------------------------------------------------------------------------


def test_vendored_procrastinate_schema_matches_the_installed_package() -> None:
    assert version("procrastinate") == "3.10.0", "procrastinate changed: add a revision with its migrations"
    vendored = (BACKEND / "alembic" / "versions" / "sql" / "procrastinate_3.10.0_schema.sql").read_text("utf-8")
    assert vendored.replace("\r\n", "\n") == SchemaManager.get_schema().replace("\r\n", "\n")


async def test_app_can_defer_fetch_and_finish_a_job(app_engine: AsyncEngine) -> None:
    async with rolled_back(app_engine) as conn:
        deferred = (
            await conn.execute(
                sa.text(
                    "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('bridge_test', 'bridge.test', 0, NULL, NULL,"
                    " '{}'::jsonb, NULL)::procrastinate_job_to_defer_v1])"
                )
            )
        ).scalar_one()
        worker = (await conn.execute(sa.text("SELECT worker_id FROM procrastinate_register_worker_v1()"))).scalar_one()
        fetched = (
            await conn.execute(
                sa.text("SELECT id FROM procrastinate_fetch_job_v2(ARRAY['bridge_test']::varchar[], :w)"),
                {"w": worker},
            )
        ).scalar_one()
        assert fetched == deferred[0]
        await conn.execute(sa.text("SELECT procrastinate_finish_job_v1(:j, 'succeeded', false)"), {"j": fetched})
        status = sa.text("SELECT status::text FROM procrastinate_jobs WHERE id = :j")
        assert (await conn.execute(status, {"j": fetched})).scalar_one() == "succeeded"


async def test_the_visibility_trigger_fires_first_on_every_tracker_table(owner_engine: AsyncEngine) -> None:
    """Triggers of one timing and event fire in name order: on every tracker table the first BEFORE INSERT row trigger
    is tracker_engagement_visible() (review P1, MAJOR 1)."""
    found = await rows(
        owner_engine,
        "SELECT DISTINCT ON (c.relname) c.relname AS table_name, p.proname AS function FROM pg_trigger t"
        " JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid"
        " WHERE NOT t.tgisinternal AND c.relname = ANY (:tables) AND t.tgtype & 7 = 7"  # ROW | BEFORE | INSERT
        ' ORDER BY c.relname, t.tgname COLLATE "C"',
        tables=[*V3_TRACKER_TABLES, "engagement_notes", *V8_THREAD_TABLES],
    )
    assert {row.table_name: row.function for row in found} == dict.fromkeys(
        (*V3_TRACKER_TABLES, "engagement_notes", *V8_THREAD_TABLES), "tracker_engagement_visible"
    )
