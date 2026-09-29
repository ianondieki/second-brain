"""Registered versions for the provenance tests, built the way the publish flow (T2.3) will: a draft with its sealed
Tier-2 row, linked problem, attachments and attestations, then draft -> registered. Rows are written as the owner role
(no RLS), with the helpers of ``tests/integration/world.py``; the pipeline under test then runs as ``bridge_app``."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.crypto.envelope import DataKey, KeyWrapper, Purpose, new_data_key, seal
from bridge.ids import uuid7
from bridge.provenance.service import new_cert_id
from tests.integration.world import add_problem, add_templates, add_user

TIER2: dict[str, Any] = {"how": "LoRa sensors report every five minutes.", "pricing": {"setup_kes": 25000}}


@dataclass(frozen=True, slots=True)
class Built:
    owner_id: UUID
    proposal_id: UUID
    version_id: UUID
    version_no: int
    cert_id: str
    niche_id: UUID
    problem_id: UUID
    key: DataKey = field(repr=False)
    attachment_hashes: tuple[bytes, ...] = ()


async def _exec(conn: AsyncConnection, sql: str, **params: object) -> None:
    await conn.execute(text(sql), params)


async def new_owner(conn: AsyncConnection) -> tuple[UUID, UUID, UUID]:
    """A developer with a handle, a niche and a published problem: (user, niche, problem)."""
    tag = uuid4().hex[:10]
    user_id = await add_user(conn, f"prov-{tag}@example.test", f"Owner {tag}")
    await _exec(conn, "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)", u=user_id, h=f"dev-{tag}")
    niche_id = uuid7()
    await _exec(
        conn,
        "INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Provenance niche')",
        id=niche_id,
        slug=f"prov-{tag}",
    )
    problem_id = await add_problem(conn, user_id, niche_id)
    return user_id, niche_id, problem_id


async def registered_version(
    engine: AsyncEngine,
    wrapper: KeyWrapper,
    *,
    tier2: Any = None,
    tier2_plaintext: bytes | None = None,
    attachments: int = 1,
    attachment_status: str = "clean",
    previous: Built | None = None,
    register: bool = True,
    tier2_row: bool = True,
) -> Built:
    """Version 1 of a new proposal, or the next version of ``previous``'s proposal (same data key)."""
    async with engine.begin() as conn:
        if previous is None:
            owner_id, niche_id, problem_id = await new_owner(conn)
            proposal_id, version_no = uuid7(), 1
            key = await new_data_key(wrapper, proposal_id)
            await _exec(
                conn,
                "INSERT INTO proposals (id, owner_id, title, niche_id) VALUES (:id, :owner, 'Cold-chain alerts', :n)",
                id=proposal_id,
                owner=owner_id,
                n=niche_id,
            )
        else:
            owner_id, niche_id, problem_id = previous.owner_id, previous.niche_id, previous.problem_id
            proposal_id, version_no, key = previous.proposal_id, previous.version_no + 1, previous.key
        version_id, cert_id = uuid7(), new_cert_id()
        await _exec(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, county_code, maturity, ask,"
            " problem_statement, impact_claims, summary) VALUES (:id, :p, :no, 'Cold-chain alerts', :n, NULL,"
            " 'prototype', 'pilot', 'Milk spoils before chilling.', NULL, 'SMS when a cooler warms.')",
            id=version_id,
            p=proposal_id,
            no=version_no,
            n=niche_id,
        )
        await _exec(
            conn,
            "INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:v, :pr)",
            v=version_id,
            pr=problem_id,
        )
        plaintext = tier2_plaintext if tier2_plaintext is not None else json.dumps(tier2 or TIER2).encode()
        sealed = seal(key, plaintext, proposal_id=proposal_id, version_id=version_id, purpose=Purpose.TIER2)
        if tier2_row:
            await _exec(
                conn,
                "INSERT INTO proposal_confidential (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek,"
                " kms_key_id) VALUES (:v, :p, :o, :c, :nonce, :w, :k)",
                v=version_id,
                p=proposal_id,
                o=owner_id,
                c=sealed.ciphertext,
                nonce=sealed.nonce,
                w=key.wrapped,
                k=key.key_id,
            )
        hashes: list[bytes] = []
        for _ in range(attachments):
            digest = hashlib.sha256(os.urandom(64)).digest()
            hashes.append(digest)
            await _exec(
                conn,
                "INSERT INTO proposal_attachments (id, owner_id, proposal_id, version_id, sha256, size_bytes,"
                " content_type, av_status) VALUES (:id, :o, :p, :v, :sha, 1024, 'application/pdf',"
                " CAST(:status AS av_status))",
                id=uuid7(),
                o=owner_id,
                p=proposal_id,
                v=version_id,
                sha=None if attachment_status == "pending_upload" else digest,
                status=attachment_status,
            )
        await _exec(
            conn,
            "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
            " no_third_party_confidential, text_version, text_sha256) VALUES (:id, :u, :v, true, true, true, 'v1',"
            " :sha)",
            id=uuid7(),
            u=owner_id,
            v=version_id,
            sha=hashlib.sha256(b"attestation text v1").digest(),
        )
        if register:
            # A draft has no owner_handle (schema v2 refuses one on INSERT); a registered version carries the owner's
            # developer handle. Schema v2 sets it at registration whatever is sent; the handle is sent for schema
            # versions that only check it is there.
            await _exec(
                conn,
                "UPDATE proposal_versions SET status = 'registered', cert_id = :cert, owner_handle ="
                " (SELECT handle FROM developer_profiles WHERE user_id = :owner) WHERE id = :id",
                id=version_id,
                cert=cert_id,
                owner=owner_id,
            )
            await _exec(
                conn,
                "UPDATE proposals SET status = 'published', current_version_id = :v, published_at = now()"
                " WHERE id = :id",
                id=proposal_id,
                v=version_id,
            )
    return Built(owner_id, proposal_id, version_id, version_no, cert_id, niche_id, problem_id, key, tuple(hashes))


async def tier2_grantee(engine: AsyncEngine, built: Built) -> UUID:
    """A reviewer of an E2 organisation who may read ``built``'s Tier 2: every condition of ``app_tier2_granted``
    holds (verified domain and an address at it, TOTP, a verified email, the current Master Enterprise Terms accepted
    by a signatory, the Evaluation NDA for this proposal, an active tier-2 grant from the owner)."""
    tag = uuid4().hex[:10]
    domain = f"grantee-{tag}.example.test"
    reviewer, signatory, org = uuid7(), uuid7(), uuid7()
    async with engine.begin() as conn:
        met_id, nda_id = await add_templates(conn, f"grantee-{tag}")  # the newest terms are the current ones
        for user_id, local in ((reviewer, "reviewer"), (signatory, "signatory")):
            await _exec(
                conn,
                "INSERT INTO users (id, email, display_name, totp_enabled_at, email_verified_at)"
                " VALUES (:id, :email, :name, now(), now())",
                id=user_id,
                email=f"{local}-{tag}@{domain}",
                name=local.title(),
            )
        await _exec(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain)"
            " VALUES (:id, 'company', 'Grantee Ltd', :slug, 'self_signup', 'e2', :domain)",
            id=org,
            slug=f"grantee-{tag}",
            domain=domain,
        )
        for user_id, roles in ((reviewer, "{reviewer}"), (signatory, "{signatory}")):
            await _exec(
                conn,
                "INSERT INTO memberships (id, org_id, user_id, roles)"
                " VALUES (:id, :org, :user, CAST(:roles AS org_role[]))",
                id=uuid7(),
                org=org,
                user=user_id,
                roles=roles,
            )
        await _exec(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE id = :template",
            id=uuid7(),
            org=org,
            user=signatory,
            template=met_id,
        )
        await _exec(
            conn,
            "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
            " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
            " WHERE id = :template",
            id=uuid7(),
            user=reviewer,
            org=org,
            proposal=built.proposal_id,
            template=nda_id,
        )
        await _exec(
            conn,
            "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source)"
            " VALUES (:id, :proposal, :org, :owner, 2, 'active', 'manual')",
            id=uuid7(),
            proposal=built.proposal_id,
            org=org,
            owner=built.owner_id,
        )
    return reviewer
