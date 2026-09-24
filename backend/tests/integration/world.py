"""A two-tenant fixture world for the RLS tests (AC-SEC-1/a).

Users A and B each own an organisation and a row in every tenant-scoped table. Rows are written as the owner role
(RLS does not apply to the table owner), so the test can then read as ``bridge_app`` and check isolation.
``TENANT_ROWS`` must cover every table whose tenancy is org, user or org_or_user; the RLS test fails otherwise, so a
new tenant table cannot ship without a fixture and a policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7


@dataclass(frozen=True, slots=True)
class Tenant:
    user_id: UUID
    org_id: UUID
    email: str


@dataclass(frozen=True, slots=True)
class World:
    a: Tenant
    b: Tenant
    niche_id: UUID
    plan_id: UUID


async def _insert(conn: AsyncConnection, sql: str, **params: object) -> None:
    await conn.execute(text(sql), params)


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
    tenants = []
    for label in ("a", "b"):
        user_id, org_id = uuid7(), uuid7()
        email = f"{label}-{tag}@example.test"
        now = datetime.now(UTC)
        await _insert(
            conn,
            "INSERT INTO users (id, email, display_name) VALUES (:id, :email, :name)",
            id=user_id,
            email=email,
            name=label.upper(),
        )
        await _insert(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source) "
            "VALUES (:id, 'company', :name, :slug, 'seed')",
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
        tenants.append(Tenant(user_id, org_id, email))
    return World(tenants[0], tenants[1], niche_id, plan_id)


# How to find the owner of a row in each tenant table: (column, kind) pairs, kind "org" or "user".
TENANT_ROWS: dict[str, str] = {
    "organizations": "SELECT id AS org, NULL::uuid AS usr FROM organizations",
    "memberships": "SELECT org_id AS org, user_id AS usr FROM memberships",
    "invitations": "SELECT org_id AS org, NULL::uuid AS usr FROM invitations",
    "org_niches": "SELECT org_id AS org, NULL::uuid AS usr FROM org_niches",
    "developer_profiles": "SELECT NULL::uuid AS org, user_id AS usr FROM developer_profiles",
    "developer_niches": "SELECT NULL::uuid AS org, user_id AS usr FROM developer_niches",
    "consents": "SELECT NULL::uuid AS org, user_id AS usr FROM consents",
    "notification_preferences": "SELECT NULL::uuid AS org, user_id AS usr FROM notification_preferences",
    "in_app_notifications": "SELECT org_id AS org, user_id AS usr FROM in_app_notifications",
    "subscriptions": "SELECT org_id AS org, user_id AS usr FROM subscriptions",
    "notification_deliveries": "SELECT org_id AS org, user_id AS usr FROM notification_deliveries",
    "audit_events": "SELECT org_id AS org, actor_user_id AS usr FROM audit_events WHERE action = 'rls.fixture'",
    "event_details": (
        "SELECT e.org_id AS org, e.actor_user_id AS usr FROM event_details d JOIN audit_events e ON e.id = d.event_id "
        "WHERE e.action = 'rls.fixture'"
    ),
}
