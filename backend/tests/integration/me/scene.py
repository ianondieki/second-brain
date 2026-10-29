"""The palette's and the calendar's world (REQ-UX-01, REQ-UX-05; P25-B): two developers, two listed organisations
(and two that are not listed), a member of each organisation and a staff admin, each with rows only they may read.

Every title holds ``word`` (a token no other module writes), so a search for it finds this scene's rows and nothing
else in the shared database. Rows are written as the owner and committed (the API reads in its own connections).

- Amina (developer): a published idea (registered, tagged to Alpha and in an engagement with it) and a draft; a team
  thread with Brian (a message each); a quiz attempt; a message on her engagement; a published problem.
- Brian (developer): a published idea (tagged to Beta, in an engagement he opened), a held one (tagged to Alpha) and a
  draft; a held and a pending problem.
- Alpha (E2): its member (finance: no second factor needed) posted a published public Brief, a draft Brief and a
  published invited-only Brief, opened the engagement with Amina (its first event), sent a message on it and opened
  Amina's full proposal once.
- Beta (E2): its owner (a role that needs two-step sign-in; TOTP on) posted a published public Brief; the same person
  is a viewer of Gamma, which is not verified (not listed). Delta is delisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

MESSAGE_GATES = ("engagement_messages",)


@dataclass(frozen=True, slots=True)
class Scene:
    word: str
    amina: UUID
    brian: UUID
    member_a: UUID  # Alpha's finance member (one organisation)
    member_b: UUID  # Beta's owner (TOTP) and Gamma's viewer: several organisations
    staff: UUID
    alpha: UUID
    beta: UUID
    gamma: UUID  # not verified: not listed
    delta: UUID  # delisted
    niche_label: str
    ideas: dict[str, UUID]  # amina_pub, amina_draft, brian_pub, brian_held, brian_draft
    problems: dict[str, UUID]  # public, held, pending, brief_a, brief_a_draft, brief_a_invited, brief_b
    tags: dict[str, UUID]  # amina_alpha, brian_beta, brian_held_alpha
    engagements: dict[str, UUID]  # amina_alpha, brian_beta

    def title(self, label: str) -> str:
        return f"{self.word} {label.replace('_', ' ')}"


async def person(conn: AsyncConnection, label: str, *, developer: bool, totp: bool = False) -> UUID:
    user = await w.add_user(conn, f"{label}-{uuid7().hex}@example.test", label.title())
    if totp:
        await t.run(conn, "UPDATE users SET totp_enabled_at = now() WHERE id = :u", u=user)
    if developer:
        await t.run(
            conn,
            "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)",
            u=user,
            h=f"{label}-{user.hex[-12:]}",
        )
    return user


async def organisation(conn: AsyncConnection, name: str, *, verification: str = "e2") -> UUID:
    org = uuid7()
    await t.run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification) VALUES (:id, 'sacco_mfi', :name,"
        " :slug, 'self_signup', CAST(:level AS org_verification))",
        id=org,
        name=name,
        slug=f"p25-{org.hex}",
        level=verification,
    )
    return org


async def niche(conn: AsyncConnection, name: str, parent: UUID | None = None) -> UUID:
    niche_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)",
        id=niche_id,
        parent=parent,
        slug=f"p25-{niche_id.hex}",
        name=name,
    )
    return niche_id


async def problem(
    conn: AsyncConnection,
    title: str,
    *,
    by: UUID,
    niche_id: UUID,
    org: UUID | None = None,
    status: str = "published",
    moderation: str = "clear",
) -> UUID:
    problem_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, org_id, moderation_state,"
        " published_at) VALUES (:id, CAST(:source AS problem_source), :niche, :title, 'A statement',"
        " CAST(:status AS problem_status), :by, :org, CAST(:moderation AS moderation_state),"
        " CASE WHEN :status = 'published' THEN now() END)",
        id=problem_id,
        source="org_brief" if org else "developer",
        niche=niche_id,
        title=title,
        status=status,
        by=by,
        org=org,
        moderation=moderation,
    )
    return problem_id


async def brief(conn: AsyncConnection, problem_id: UUID, org: UUID, *, visibility: str, status: str) -> None:
    await t.run(
        conn,
        "INSERT INTO problem_briefs (problem_id, org_id, visibility, status)"
        " VALUES (:p, :o, CAST(:v AS brief_visibility), CAST(:s AS brief_status))",
        p=problem_id,
        o=org,
        v=visibility,
        s=status,
    )


async def idea(
    conn: AsyncConnection,
    owner: UUID,
    title: str,
    *,
    niche_id: UUID,
    problem_id: UUID,
    registered: bool = True,
    moderation: str = "clear",
) -> tuple[UUID, UUID]:
    """A proposal with one version titled ``title``: registered and published, or a draft."""
    proposal_id, version_id = uuid7(), uuid7()
    await t.run(
        conn,
        "INSERT INTO proposals (id, owner_id, moderation_state, title, niche_id) VALUES (:id, :owner,"
        " CAST(:moderation AS moderation_state), :title, :niche)",
        id=proposal_id,
        owner=owner,
        moderation=moderation,
        title=title,
        niche=niche_id,
    )
    await t.run(
        conn,
        "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask, problem_statement,"
        " summary) VALUES (:id, :proposal, 1, :title, :niche, 'idea', 'pilot', 'A problem', 'What it does')",
        id=version_id,
        proposal=proposal_id,
        title=title,
        niche=niche_id,
    )
    await t.run(
        conn,
        "INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:v, :p)",
        v=version_id,
        p=problem_id,
    )
    if registered:
        await t.run(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :cert WHERE id = :id",
            id=version_id,
            cert=uuid7().hex[:16],
        )
        await t.run(
            conn,
            "UPDATE proposals SET status = 'published', current_version_id = :v, published_at = now() WHERE id = :id",
            id=proposal_id,
            v=version_id,
        )
    else:
        await t.run(conn, "UPDATE proposals SET draft_version_id = :v WHERE id = :id", id=proposal_id, v=version_id)
    return proposal_id, version_id


async def engagement(
    conn: AsyncConnection, *, proposal: UUID, version: UUID, org: UUID, developer: UUID, opened_by: UUID
) -> UUID:
    """An engagement in SUBMITTED whose first event (the database's) names ``opened_by`` as its actor."""
    engagement_id = uuid7()
    await t.run(conn, "SELECT set_config('app.user_id', :u, true)", u=str(opened_by))
    await t.run(
        conn,
        t.ENGAGE,
        id=engagement_id,
        p=proposal,
        org=org,
        dev=developer,
        v=version,
        origin="tagged",
        state="SUBMITTED",
    )
    await t.run(conn, "SELECT set_config('app.user_id', '', true)")
    return engagement_id


async def message(conn: AsyncConnection, engagement_id: UUID, sender: UUID, party: str) -> None:
    """A message on an engagement before its thread opens (the stage gate is off for this insert only)."""
    await t.run(conn, "ALTER TABLE engagement_messages DISABLE TRIGGER engagement_messages_1_open")
    await t.run(
        conn,
        "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
        " VALUES (:id, :e, :s, CAST(:party AS engagement_party), 'When can we meet?')",
        id=uuid7(),
        e=engagement_id,
        s=sender,
        party=party,
    )
    await t.run(conn, "ALTER TABLE engagement_messages ENABLE TRIGGER engagement_messages_1_open")


async def full_proposal_view(
    conn: AsyncConnection, *, viewer: UUID, org: UUID, owner: UUID, proposal: UUID, version: UUID, word: str
) -> None:
    """``viewer`` opened ``proposal``'s full text for ``org`` once (an accepted NDA and a logged view)."""
    _, nda_template = await w.add_templates(conn, word)
    acceptance = uuid7()
    await t.run(
        conn,
        "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
        " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
        " WHERE id = :template",
        id=acceptance,
        user=viewer,
        org=org,
        proposal=proposal,
        template=nda_template,
    )
    await t.run(
        conn,
        "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id, nda_acceptance_id,"
        " render_kind, fingerprint_seed) VALUES (:id, :proposal, :version, :owner, :viewer, :org, :nda, 'html', :seed)",
        id=uuid7(),
        proposal=proposal,
        version=version,
        owner=owner,
        viewer=viewer,
        org=org,
        nda=acceptance,
        seed=uuid7().bytes,
    )


async def build(owner_engine: AsyncEngine) -> Scene:
    word = f"zq{uuid7().hex[-10:]}"
    async with owner_engine.begin() as conn:
        amina = await person(conn, "amina", developer=True)
        brian = await person(conn, "brian", developer=True)
        member_a = await person(conn, "membera", developer=False)
        member_b = await person(conn, "memberb", developer=False, totp=True)
        staff = await w.add_user(conn, f"staff-{uuid7().hex}@example.test", "Staff", staff_role="admin")
        alpha = await organisation(conn, f"{word} Alpha Sacco Ltd")
        beta = await organisation(conn, f"{word} Beta Telco Ltd")
        gamma = await organisation(conn, f"{word} Gamma Hidden Ltd", verification="pending")
        delta = await organisation(conn, f"{word} Delta Gone Ltd")
        await t.run(conn, "UPDATE organizations SET delisted_at = now() WHERE id = :o", o=delta)
        await t.member(conn, alpha, member_a, "{finance}")
        await t.member(conn, beta, member_b, "{owner,admin}")
        await t.member(conn, gamma, member_b, "{viewer}")
        parent = await niche(conn, f"{word} Finance")
        child = await niche(conn, f"{word} SACCOs", parent)
        scene = Scene(
            word, amina, brian, member_a, member_b, staff, alpha, beta, gamma, delta,
            f"{word} Finance › {word} SACCOs", {}, {}, {}, {},
        )  # fmt: skip
        problems = scene.problems
        problems["public"] = await problem(conn, scene.title("water_queues"), by=amina, niche_id=child)
        problems["held"] = await problem(conn, scene.title("held_problem"), by=brian, niche_id=child, moderation="held")
        problems["pending"] = await problem(
            conn, scene.title("pending_problem"), by=brian, niche_id=child, status="pending_review"
        )
        for label, org, by, visibility, status in (
            ("brief_a", alpha, member_a, "public", "published"),
            ("brief_a_draft", alpha, member_a, "public", "draft"),
            ("brief_a_invited", alpha, member_a, "invited", "published"),
            ("brief_b", beta, member_b, "public", "published"),
        ):
            pending = status == "draft"
            problems[label] = await problem(
                conn,
                scene.title(label),
                by=by,
                niche_id=child,
                org=org,
                status="pending_review" if pending else "published",
            )
            await brief(conn, problems[label], org, visibility=visibility, status=status)
        ideas, versions = scene.ideas, {}
        for label, owner, registered, moderation in (
            ("amina_pub", amina, True, "clear"),
            ("amina_draft", amina, False, "clear"),
            ("brian_pub", brian, True, "clear"),
            ("brian_held", brian, True, "held"),
            ("brian_draft", brian, False, "clear"),
        ):
            ideas[label], versions[label] = await idea(
                conn,
                owner,
                scene.title(label),
                niche_id=child,
                problem_id=problems["public"],
                registered=registered,
                moderation=moderation,
            )
        scene.tags["amina_alpha"] = await t.tag(conn, ideas["amina_pub"], alpha, amina)
        scene.tags["brian_beta"] = await t.tag(conn, ideas["brian_pub"], beta, brian)
        scene.tags["brian_held_alpha"] = await t.tag(conn, ideas["brian_held"], alpha, brian)
        scene.engagements["amina_alpha"] = await engagement(
            conn,
            proposal=ideas["amina_pub"],
            version=versions["amina_pub"],
            org=alpha,
            developer=amina,
            opened_by=member_a,
        )
        scene.engagements["brian_beta"] = await engagement(
            conn, proposal=ideas["brian_pub"], version=versions["brian_pub"], org=beta, developer=brian, opened_by=brian
        )
        await message(conn, scene.engagements["amina_alpha"], amina, "developer")
        await message(conn, scene.engagements["amina_alpha"], member_a, "org")
        await w.add_team_rows(conn, amina, brian, problems["public"], (), word)
        await w.add_quiz_rows(conn, staff, [amina])
        await full_proposal_view(
            conn,
            viewer=member_a,
            org=alpha,
            owner=amina,
            proposal=ideas["amina_pub"],
            version=versions["amina_pub"],
            word=word,
        )
    return scene
