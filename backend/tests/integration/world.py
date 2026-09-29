"""A two-tenant fixture world for the RLS tests (AC-SEC-1/a, AC-SEC-1/b).

Users A and B each own an organisation and rows in every tenant-scoped table; a staff admin exists for the STAFF
tables. Rows are written as the owner role (RLS does not apply to the table owner), so the tests can then read as
``bridge_app`` (or the table's ``db_role``) and check isolation.

``TENANT_ROWS`` must cover every table whose tenancy is org, user, org_or_user or published, and ``STAFF_ROWS`` every
staff table; the RLS tests fail otherwise, so a new tenant table cannot ship without a fixture and a policy. For the
PUBLISHED tables each tenant has rows every signed-in user may read (published, clear) and rows only its owner may
read (drafts, held, hidden, candidate), so the tests prove both halves of the rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7

FIXTURE = "rls-fixture"  # marks the fixture rows of tables with no tenant column (staff tables)
VECTOR_1024 = "CAST(array_fill(CAST(0.001 AS real), ARRAY[1024]) AS vector)"


@dataclass(frozen=True, slots=True)
class Tenant:
    user_id: UUID
    org_id: UUID
    email: str
    # Proposals by visibility (docs/spec/06 6.1): only ``published`` is readable by other signed-in users.
    published: UUID
    draft: UUID
    held: UUID
    hidden: UUID
    published_version: UUID
    draft_version: UUID


@dataclass(frozen=True, slots=True)
class World:
    a: Tenant
    b: Tenant
    niche_id: UUID
    plan_id: UUID
    staff_id: UUID  # staff admin with TOTP enrolled
    met_template_id: UUID  # Master Enterprise Terms of this world
    nda_template_id: UUID  # Evaluation NDA of this world


async def _insert(conn: AsyncConnection, sql: str, **params: object) -> None:
    await conn.execute(text(sql), params)


async def add_user(conn: AsyncConnection, email: str, name: str, *, staff_role: str | None = None) -> UUID:
    """A user; staff get TOTP enrolled (app_is_staff() requires it)."""
    user_id = uuid7()
    await _insert(
        conn,
        "INSERT INTO users (id, email, display_name, staff_role, totp_enabled_at)"
        " VALUES (:id, :email, :name, CAST(:staff AS staff_role), :totp)",
        id=user_id,
        email=email,
        name=name,
        staff=staff_role,
        totp=datetime.now(UTC) if staff_role else None,
    )
    return user_id


async def add_templates(conn: AsyncConnection, tag: str) -> tuple[UUID, UUID]:
    """A Master Enterprise Terms and an Evaluation NDA version of this world (placeholder bodies)."""
    met_id, legal_nda_id, nda_id = uuid7(), uuid7(), uuid7()
    for template_id, kind in ((met_id, "master_enterprise_terms"), (legal_nda_id, "evaluation_nda")):
        await _insert(
            conn,
            "INSERT INTO legal_templates (id, kind, version, body, sha256)"
            " VALUES (:id, CAST(:kind AS legal_template_kind), :version, :body, sha256(convert_to(:body, 'UTF8')))",
            id=template_id,
            kind=kind,
            version=f"rls-{tag}",
            body=f"[[LEGAL-PLACEHOLDER:{kind}-{tag}]]\n",
        )
    await _insert(
        conn,
        "INSERT INTO nda_templates (id, kind, version, legal_template_id, sha256)"
        " SELECT :id, 'evaluation', :version, id, sha256 FROM legal_templates WHERE id = :legal",
        id=nda_id,
        version=f"rls-{tag}",
        legal=legal_nda_id,
    )
    return met_id, nda_id


async def add_proposal(
    conn: AsyncConnection,
    owner: UUID,
    niche_id: UUID,
    problem_id: UUID,
    *,
    status: str = "published",
    moderation_state: str = "clear",
    registered: bool = True,
) -> tuple[UUID, UUID]:
    """A proposal with one version (and its Tier-2 row). Registered versions go draft -> registered like the app,
    which gives them the owner's developer handle (the owner gets a developer profile if they have none)."""
    proposal_id, version_id = uuid7(), uuid7()
    await _insert(
        conn,
        "INSERT INTO developer_profiles (user_id, handle) VALUES (:owner, :handle) ON CONFLICT (user_id) DO NOTHING",
        owner=owner,
        handle=f"dev-{owner.hex}",
    )
    await _insert(
        conn,
        "INSERT INTO proposals (id, owner_id, moderation_state, title, niche_id) VALUES (:id, :owner,"
        " CAST(:moderation AS moderation_state), 'RLS proposal', :niche)",
        id=proposal_id,
        owner=owner,
        moderation=moderation_state,
        niche=niche_id,
    )
    await _insert(
        conn,
        "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask, problem_statement,"
        " summary) VALUES (:id, :proposal, 1, 'RLS proposal', :niche, 'idea', 'pilot', 'A problem', 'What it does')",
        id=version_id,
        proposal=proposal_id,
        niche=niche_id,
    )
    await _insert(
        conn,
        "INSERT INTO proposal_confidential"
        " (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek, kms_key_id)"
        " VALUES (:version, :proposal, :owner, '\\x01', '\\x02', '\\x03', 'local:test')",
        version=version_id,
        proposal=proposal_id,
        owner=owner,
    )
    await _insert(
        conn,
        "INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:version, :problem)",
        version=version_id,
        problem=problem_id,
    )
    if registered:
        await _insert(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :cert, registered_at = now() WHERE id = :id",
            id=version_id,
            cert=uuid7().hex[:16],
        )
        await _insert(
            conn,
            "UPDATE proposals SET status = CAST(:status AS proposal_status), current_version_id = :version,"
            " published_at = now() WHERE id = :id",
            id=proposal_id,
            status=status,
            version=version_id,
        )
    else:
        await _insert(
            conn, "UPDATE proposals SET draft_version_id = :version WHERE id = :id", id=proposal_id, version=version_id
        )
    return proposal_id, version_id


async def add_problem(
    conn: AsyncConnection,
    user_id: UUID,
    niche_id: UUID,
    *,
    org_id: UUID | None = None,
    status: str = "published",
    moderation_state: str = "clear",
) -> UUID:
    problem_id = uuid7()
    await _insert(
        conn,
        "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, org_id, moderation_state)"
        " VALUES (:id, CAST(:source AS problem_source), :niche, 'RLS problem', 'Statement',"
        " CAST(:status AS problem_status), :user, :org, CAST(:moderation AS moderation_state))",
        id=problem_id,
        source="org_brief" if org_id else "developer",
        niche=niche_id,
        status=status,
        user=user_id,
        org=org_id,
        moderation=moderation_state,
    )
    await _insert(
        conn,
        "INSERT INTO problem_sources (id, problem_id, url, retrieved_at) VALUES (:id, :problem, :url, now())",
        id=uuid7(),
        problem=problem_id,
        url="https://example.test/source",
    )
    return problem_id


async def build(conn: AsyncConnection, tag: str) -> World:
    """Create the world inside ``conn`` (owner role). ``tag`` keeps emails and slugs unique per test session."""
    niche_id, plan_id = uuid7(), uuid7()
    await _insert(
        conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'RLS niche')", id=niche_id, slug=f"rls-{tag}"
    )
    await _insert(
        conn,
        "INSERT INTO plans (id, code, side, name, price_kes_minor, interval, limits) "
        "VALUES (:id, :code, 'org', 'RLS plan', 0, 'none', '{}')",
        id=plan_id,
        code=f"rls-{tag}",
    )
    staff_id = await add_user(conn, f"staff-{tag}@example.test", "Staff", staff_role="admin")
    met_id, nda_template_id = await add_templates(conn, tag)
    tenants = []
    for label in ("a", "b"):
        org_id = uuid7()
        email = f"{label}-{tag}@example.test"
        now = datetime.now(UTC)
        user_id = await add_user(conn, email, label.upper())
        await _insert(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source) "
            "VALUES (:id, 'company', :name, :slug, 'self_signup')",
            id=org_id,
            name=f"Org {label.upper()}",
            slug=f"org-{label}-{tag}",
        )
        await _insert(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{owner,admin}')",
            id=uuid7(),
            org=org_id,
            user=user_id,
        )
        await _insert(
            conn,
            "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at) "
            "VALUES (:id, :org, :email, '{viewer}', :hash, :user, :exp)",
            id=uuid7(),
            org=org_id,
            email=f"invitee-{label}-{tag}@example.test",
            hash=uuid7().bytes,
            user=user_id,
            exp=now,
        )
        await _insert(
            conn, "INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)", org=org_id, niche=niche_id
        )
        await _insert(
            conn,
            "INSERT INTO developer_profiles (user_id, handle) VALUES (:user, :handle)",
            user=user_id,
            handle=f"h-{label}-{tag}",
        )
        await _insert(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:user, :niche, 'liked')",
            user=user_id,
            niche=niche_id,
        )
        await _insert(
            conn,
            "INSERT INTO consents (id, user_id, purpose, granted, text_version, text_sha256, source) "
            "VALUES (:id, :user, 'marketing', true, 'v1', :sha, 'test')",
            id=uuid7(),
            user=user_id,
            sha=bytes(32),
        )
        await _insert(
            conn,
            "INSERT INTO notification_preferences (user_id, kind, channel) VALUES (:user, 'em7', 'email')",
            user=user_id,
        )
        await _insert(
            conn,
            "INSERT INTO in_app_notifications (id, user_id, kind, title) VALUES (:id, :user, 'test', 'Hello')",
            id=uuid7(),
            user=user_id,
        )
        for scope in ("user", "org"):
            await _insert(
                conn,
                "INSERT INTO subscriptions (id, user_id, org_id, plan_id, status, current_period_start) "
                "VALUES (:id, :user, :org, :plan, 'active', :now)",
                id=uuid7(),
                user=user_id if scope == "user" else None,
                org=org_id if scope == "org" else None,
                plan=plan_id,
                now=now,
            )
            await _insert(
                conn,
                "INSERT INTO notification_deliveries (id, user_id, org_id, kind, channel, to_address) "
                "VALUES (:id, :user, :org, 'test', 'email', 'x@example.test')",
                id=uuid7(),
                user=user_id if scope == "user" else None,
                org=org_id if scope == "org" else None,
            )
            await _insert(
                conn,
                "INSERT INTO llm_calls (id, user_id, org_id, task, model, status) "
                "VALUES (:id, :user, :org, 'rls.fixture', 'fake', 'ok')",
                id=uuid7(),
                user=user_id if scope == "user" else None,
                org=org_id if scope == "org" else None,
            )
        event_id = uuid7()
        await _insert(
            conn,
            "INSERT INTO audit_events (id, seq, actor_kind, actor_user_id, org_id, action, prev_hash, event_hash) "
            "VALUES (:id, 0, 'user', :user, :org, 'rls.fixture', ''::bytea, ''::bytea)",
            id=event_id,
            user=user_id,
            org=org_id,
        )
        await _insert(conn, "INSERT INTO event_details (event_id, details) VALUES (:id, '{}')", id=event_id)

        # --- Schema v2 (revision 0002) ---
        # Problems: public (published, clear), held, a Brief awaiting review, and a public published Brief.
        public_problem = await add_problem(conn, user_id, niche_id)
        await add_problem(conn, user_id, niche_id, moderation_state="held")
        invited_brief = await add_problem(conn, user_id, niche_id, org_id=org_id, status="pending_review")
        public_brief = await add_problem(conn, user_id, niche_id, org_id=org_id)
        for brief_id, visibility, status in (
            (invited_brief, "invited", "draft"),
            (public_brief, "public", "published"),
        ):
            await _insert(
                conn,
                "INSERT INTO problem_briefs (problem_id, org_id, visibility, status) VALUES (:id, :org,"
                " CAST(:visibility AS brief_visibility), CAST(:status AS brief_status))",
                id=brief_id,
                org=org_id,
                visibility=visibility,
                status=status,
            )
        await _insert(
            conn,
            "INSERT INTO brief_invitations (id, brief_id, org_id, user_id) VALUES (:id, :brief, :org, :user)",
            id=uuid7(),
            brief=invited_brief,
            org=org_id,
            user=user_id,
        )
        # Proposals: published and clear (public), a draft, a held one and a hidden ("deleted") one.
        published, published_version = await add_proposal(conn, user_id, niche_id, public_problem)
        draft, draft_version = await add_proposal(conn, user_id, niche_id, public_problem, registered=False)
        held, _ = await add_proposal(conn, user_id, niche_id, public_problem, moderation_state="held")
        hidden, _ = await add_proposal(conn, user_id, niche_id, public_problem, status="hidden")
        for band, proposal in enumerate((published, draft, held, hidden)):  # originality buckets of each teaser
            await _insert(
                conn,
                "INSERT INTO proposal_lsh_bands (proposal_id, band, bucket) VALUES (:proposal, :band, :bucket)",
                proposal=proposal,
                band=band,
                bucket=band + 1,
            )
        await _insert(
            conn,
            "INSERT INTO proposal_confidential_embeddings (version_id, embed_model, embed_version, full_embedding)"
            f" VALUES (:version, '{FIXTURE}', '1', {VECTOR_1024})",
            version=published_version,
        )
        await _insert(
            conn,
            "INSERT INTO proposal_attachments (id, owner_id, proposal_id, version_id, content_type)"
            " VALUES (:id, :owner, :proposal, :version, 'application/pdf')",
            id=uuid7(),
            owner=user_id,
            proposal=draft,
            version=draft_version,
        )
        await _insert(
            conn,
            "INSERT INTO originality_checks (id, user_id, band) VALUES (:id, :user, 'none')",
            id=uuid7(),
            user=user_id,
        )
        await _insert(
            conn,
            "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
            " no_third_party_confidential, text_version, text_sha256) VALUES (:id, :user, :version, true, true, true,"
            " 'v1', :sha)",
            id=uuid7(),
            user=user_id,
            version=published_version,
            sha=bytes(32),
        )
        await _insert(
            conn,
            "INSERT INTO tags (id, proposal_id, org_id, developer_id, status) VALUES (:id, :proposal, :org, :user,"
            " 'delivered')",
            id=uuid7(),
            proposal=published,
            org=org_id,
            user=user_id,
        )
        await _insert(
            conn,
            "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state)"
            " VALUES (:id, :proposal, :org, :user, :version, 'tagged', 'SUBMITTED')",
            id=uuid7(),
            proposal=published,
            org=org_id,
            user=user_id,
            version=published_version,
        )
        await _insert(
            conn,
            "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source)"
            " VALUES (:id, :proposal, :org, :user, 2, 'active', 'auto_tagged')",
            id=uuid7(),
            proposal=published,
            org=org_id,
            user=user_id,
        )
        nda_acceptance = uuid7()
        await _insert(
            conn,
            "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
            " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
            " WHERE id = :template",
            id=nda_acceptance,
            user=user_id,
            org=org_id,
            proposal=published,
            template=nda_template_id,
        )
        await _insert(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE id = :template",
            id=uuid7(),
            org=org_id,
            user=user_id,
            template=met_id,
        )
        await _insert(
            conn,
            "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id,"
            " nda_acceptance_id, render_kind, fingerprint_seed) VALUES (:id, :proposal, :version, :user, :user, :org,"
            " :nda, 'html', :seed)",
            id=uuid7(),
            proposal=published,
            version=published_version,
            user=user_id,
            org=org_id,
            nda=nda_acceptance,
            seed=uuid7().bytes,
        )
        await _insert(
            conn,
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :user, :domain, :email, 'e2', 'pending_review')",
            id=uuid7(),
            org=org_id,
            user=user_id,
            domain=f"{label}-{tag}.example.test",
            email=f"claims@{label}-{tag}.example.test",
        )
        await _insert(
            conn,
            "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash, expires_at)"
            " VALUES (:id, :user, '+254700000000', :hash, :exp)",
            id=uuid7(),
            user=user_id,
            hash=bytes(32),
            exp=now + timedelta(minutes=10),
        )
        await _insert(conn, "INSERT INTO kyc_reviews (id, user_id) VALUES (:id, :user)", id=uuid7(), user=user_id)
        # Staff tables: fixture rows about this tenant, marked so the tests find them.
        await _insert(
            conn,
            "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source)"
            f" VALUES (:id, 'proposal', :subject, '{{{FIXTURE}}}', 'regex')",
            id=uuid7(),
            subject=held,
        )
        await _insert(
            conn,
            "INSERT INTO directory_invitations (id, org_id, to_address, reason)"
            f" VALUES (:id, :org, :address, '{FIXTURE}')",
            id=uuid7(),
            org=org_id,
            address=f"partnerships@{label}-{tag}.example.test",
        )
        tenants.append(Tenant(user_id, org_id, email, published, draft, held, hidden, published_version, draft_version))
    # A system LLM call (no user, no organisation): readable by staff admin only.
    await _insert(
        conn,
        "INSERT INTO llm_calls (id, task, model, status) VALUES (:id, 'rls.fixture', 'fake', 'ok')",
        id=uuid7(),
    )
    return World(tenants[0], tenants[1], niche_id, plan_id, staff_id, met_id, nda_template_id)


@dataclass(frozen=True, slots=True)
class Rows:
    """How the RLS tests find a table's fixture rows.

    ``key`` is a SQL expression over the table that identifies a row; the tests read it as a tenant, under RLS.
    ``owners`` returns ``key, org, usr, pub`` for every fixture row; the tests read it as the owner (no RLS), so the
    attribution never depends on what RLS lets the tenant join to. ``pub`` marks a row every signed-in user may read.
    """

    key: str
    owners: str


def _rows(table: str, key: str, org: str, usr: str, pub: str = "false", where: str = "") -> Rows:
    owners = f"SELECT {key} AS key, {org} AS org, {usr} AS usr, {pub} AS pub FROM {table} t"
    return Rows(key=key.replace("t.", f"{table}."), owners=owners + (f" WHERE {where}" if where else ""))


NO_ORG, NO_USER = "CAST(NULL AS uuid)", "CAST(NULL AS uuid)"
# Readable by every signed-in user (docs/spec/06 6.1, 6.2): the rules restated from the spec, not from the policies.
_PUBLIC_PROBLEM = (
    "t.status = 'published' AND t.moderation_state = 'clear' AND (t.org_id IS NULL OR EXISTS (SELECT 1"
    " FROM problem_briefs b WHERE b.problem_id = t.id AND b.visibility = 'public' AND b.status = 'published'))"
)
_PUBLIC_PROPOSAL = "p.status = 'published' AND p.moderation_state = 'clear'"

TENANT_ROWS: dict[str, Rows] = {
    # revision 0001
    "organizations": _rows(
        "organizations",
        "t.id::text",
        "t.id",
        NO_USER,
        "t.verification IN ('unclaimed', 'e1', 'e2') AND t.delisted_at IS NULL",
    ),
    "memberships": _rows("memberships", "t.id::text", "t.org_id", "t.user_id"),
    "invitations": _rows("invitations", "t.id::text", "t.org_id", NO_USER),
    "org_niches": _rows("org_niches", "t.org_id::text || t.niche_id::text", "t.org_id", NO_USER),
    "developer_profiles": _rows("developer_profiles", "t.user_id::text", NO_ORG, "t.user_id"),
    "developer_niches": _rows(
        "developer_niches", "t.user_id::text || t.niche_id::text || t.kind::text", NO_ORG, "t.user_id"
    ),
    "consents": _rows("consents", "t.id::text", NO_ORG, "t.user_id"),
    "notification_preferences": _rows(
        "notification_preferences", "t.user_id::text || t.kind || t.channel::text", NO_ORG, "t.user_id"
    ),
    "in_app_notifications": _rows("in_app_notifications", "t.id::text", "t.org_id", "t.user_id"),
    "subscriptions": _rows("subscriptions", "t.id::text", "t.org_id", "t.user_id"),
    "notification_deliveries": _rows("notification_deliveries", "t.id::text", "t.org_id", "t.user_id"),
    "audit_events": _rows(
        "audit_events", "t.id::text", "t.org_id", "t.actor_user_id", where="t.action = 'rls.fixture'"
    ),
    "event_details": Rows(
        key="event_details.event_id::text",
        owners="SELECT t.event_id::text AS key, e.org_id AS org, e.actor_user_id AS usr, false AS pub"
        " FROM event_details t JOIN audit_events e ON e.id = t.event_id WHERE e.action = 'rls.fixture'",
    ),
    # revision 0002: PUBLISHED
    "problems": _rows("problems", "t.id::text", "t.org_id", "t.created_by", _PUBLIC_PROBLEM),
    "problem_sources": Rows(
        key="problem_sources.id::text",
        owners="SELECT s.id::text AS key, t.org_id AS org, t.created_by AS usr, "
        + _PUBLIC_PROBLEM
        + " AS pub FROM problem_sources s JOIN problems t ON t.id = s.problem_id",
    ),
    "proposals": Rows(
        key="proposals.id::text",
        owners=f"SELECT p.id::text AS key, {NO_ORG} AS org, p.owner_id AS usr, {_PUBLIC_PROPOSAL} AS pub"
        " FROM proposals p",
    ),
    "proposal_versions": Rows(
        key="proposal_versions.id::text",
        owners=f"SELECT v.id::text AS key, {NO_ORG} AS org, p.owner_id AS usr,"
        f" v.status = 'registered' AND {_PUBLIC_PROPOSAL} AS pub"
        " FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id",
    ),
    "proposal_lsh_bands": Rows(
        key="proposal_lsh_bands.proposal_id::text || proposal_lsh_bands.band::text",
        owners=f"SELECT l.proposal_id::text || l.band::text AS key, {NO_ORG} AS org, p.owner_id AS usr,"
        f" {_PUBLIC_PROPOSAL} AS pub FROM proposal_lsh_bands l JOIN proposals p ON p.id = l.proposal_id",
    ),
    "proposal_problems": Rows(
        key="proposal_problems.proposal_version_id::text || proposal_problems.problem_id::text",
        owners=f"SELECT pp.proposal_version_id::text || pp.problem_id::text AS key, {NO_ORG} AS org,"
        f" p.owner_id AS usr, v.status = 'registered' AND {_PUBLIC_PROPOSAL} AS pub FROM proposal_problems pp"
        " JOIN proposal_versions v ON v.id = pp.proposal_version_id JOIN proposals p ON p.id = v.proposal_id",
    ),
    # revision 0002: ORG, USER and ORG_OR_USER
    "problem_briefs": _rows(
        "problem_briefs",
        "t.problem_id::text",
        "t.org_id",
        NO_USER,
        "t.visibility = 'public' AND t.status = 'published'",
    ),
    "brief_invitations": _rows("brief_invitations", "t.id::text", "t.org_id", "t.user_id"),
    "proposal_confidential": _rows("proposal_confidential", "t.version_id::text", NO_ORG, "t.owner_id"),
    "proposal_attachments": _rows("proposal_attachments", "t.id::text", NO_ORG, "t.owner_id"),
    "originality_checks": _rows("originality_checks", "t.id::text", NO_ORG, "t.user_id"),
    "attestations": _rows("attestations", "t.id::text", NO_ORG, "t.user_id"),
    "phone_verifications": _rows("phone_verifications", "t.id::text", NO_ORG, "t.user_id"),
    "kyc_reviews": _rows("kyc_reviews", "t.id::text", NO_ORG, "t.user_id"),
    "tags": _rows("tags", "t.id::text", "t.org_id", "t.developer_id"),
    "engagements": _rows("engagements", "t.id::text", "t.org_id", "t.developer_id"),
    "disclosure_grants": _rows("disclosure_grants", "t.id::text", "t.org_id", "t.owner_id"),
    "nda_acceptances": _rows("nda_acceptances", "t.id::text", "t.org_id", "t.user_id"),
    "legal_acceptances": _rows("legal_acceptances", "t.id::text", "t.org_id", "t.user_id"),
    "document_views": _rows("document_views", "t.id::text", "t.org_id", "t.viewer_user_id"),
    "org_claims": _rows("org_claims", "t.id::text", "t.org_id", "t.claimant_user_id"),
    "llm_calls": _rows("llm_calls", "t.id::text", "t.org_id", "t.user_id", where="t.task = 'rls.fixture'"),
}

# STAFF tables: (key expression, owner query returning the keys of the fixture rows).
STAFF_ROWS: dict[str, Rows] = {
    "moderation_cases": Rows(
        key="moderation_cases.id::text",
        owners=f"SELECT id::text AS key FROM moderation_cases WHERE reasons @> '{{{FIXTURE}}}'",
    ),
    "directory_invitations": Rows(
        key="directory_invitations.id::text",
        owners=f"SELECT id::text AS key FROM directory_invitations WHERE reason = '{FIXTURE}'",
    ),
    "proposal_confidential_embeddings": Rows(
        key="proposal_confidential_embeddings.version_id::text",
        owners=f"SELECT version_id::text AS key FROM proposal_confidential_embeddings WHERE embed_model = '{FIXTURE}'",
    ),
}
