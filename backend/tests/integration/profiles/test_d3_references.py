"""REQ-DEV-04 (P27 track E; docs/spec/06 6.4 pt 8 "D3 optional GitHub/KECOBO/KIPI numbers shown as self-reported"):
a developer saves, changes and clears their GitHub login and KECOBO and KIPI references on their profile; an invalid
login or reference is refused 422 (never quoting it) and nothing is saved; the authorship certificate's PDF carries
the "Self-reported references" row when any is set, and the public verify API never carries them. The IP nudge's
dismissal is idempotent and the developer's own."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import create_session_factory
from bridge.provenance.service import hash_manifest
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.api import make_client, sign_in_as
from tests.integration.engagements.api_world import build as tracker_world
from tests.integration.provenance.builders import Built, registered_version
from tests.unit.provenance.test_certificate import pdf_text

LOGIN = "octo-cat-42"
KECOBO = "KECOBO/LIT/2026/0042"
KIPI = "KE/U/2026/000123"


@pytest.fixture
async def built(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> Built:
    """A registered version with its hashed manifest (its provenance record: the certificate's facts)."""
    wrapper = LocalKeyWrapper(os.urandom(32))
    version = await registered_version(owner_engine, wrapper, attachments=0)
    async with create_session_factory(app_engine)() as session:
        assert await hash_manifest(
            session, version.version_id, version.owner_id, wrapper=wrapper, store=InMemoryObjectStore()
        )
    return version


@pytest.fixture
async def dev(app_engine: AsyncEngine, built: Built) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine, ip="127.0.7.1") as client:
        await sign_in_as(client, app_engine, built.owner_id, mfa_verified=False)
        yield client


async def stored(owner_engine: AsyncEngine, user: UUID) -> tuple[str | None, str | None, str | None]:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT github_login, kecobo_number, kipi_number FROM developer_profiles WHERE user_id = :u"),
                {"u": user},
            )
        ).one()
    return row.github_login, row.kecobo_number, row.kipi_number


async def test_a_developer_saves_changes_and_clears_their_references(
    dev: httpx.AsyncClient, owner_engine: AsyncEngine, built: Built
) -> None:
    before = (await dev.get("/api/me/profile")).json()
    assert (before["github_login"], before["kecobo_number"], before["kipi_number"]) == (None, None, None)
    saved = await dev.patch(
        "/api/me/profile", json={"github_login": LOGIN, "kecobo_number": f"  {KECOBO} ", "kipi_number": KIPI}
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["github_login"], saved.json()["kecobo_number"], saved.json()["kipi_number"]) == (
        LOGIN,
        KECOBO,  # trimmed
        KIPI,
    )
    assert await stored(owner_engine, built.owner_id) == (LOGIN, KECOBO, KIPI)
    read = (await dev.get("/api/me/profile")).json()
    assert (read["github_login"], read["kecobo_number"], read["kipi_number"]) == (LOGIN, KECOBO, KIPI)

    # a null clears one; an empty value clears another; what is not sent stays
    cleared = await dev.patch("/api/me/profile", json={"github_login": None, "kipi_number": ""})
    assert cleared.status_code == 200, cleared.text
    assert await stored(owner_engine, built.owner_id) == (None, KECOBO, None)
    assert (await dev.patch("/api/me/profile", json={"headline": "Builder"})).status_code == 200
    assert await stored(owner_engine, built.owner_id) == (None, KECOBO, None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("github_login", "-octo"),
        ("github_login", "octo-"),
        ("github_login", "oc--to"),
        ("github_login", "octo_cat"),
        ("github_login", "octo cat"),
        ("github_login", "@@octo"),  # one leading @ is GitHub's mention sign, not part of the login; two are wrong
        ("github_login", "@-octo"),
        ("github_login", "@"),
        ("github_login", "@ octo"),
        ("github_login", "octo@"),
        ("github_login", "a" * 40),
        ("github_login", "\u043ecto"),  # a Cyrillic o
        ("kecobo_number", "K" * 41),
        ("kecobo_number", "line\nbreak"),
        ("kecobo_number", "tab\there"),
        ("kipi_number", "zero\u200bwidth"),
        ("kipi_number", "no\u00a0break"),
        ("kipi_number", "bidi\u202eKE"),
        ("kipi_number", "\ufeffKE/U/1"),
    ],
)
async def test_an_invalid_login_or_reference_is_refused(
    dev: httpx.AsyncClient, owner_engine: AsyncEngine, built: Built, field: str, value: str
) -> None:
    refused = await dev.patch("/api/me/profile", json={field: value})
    assert refused.status_code == 422, refused.text
    assert value not in refused.text  # the 422 never quotes the value it refused
    assert await stored(owner_engine, built.owner_id) == (None, None, None)


async def test_the_longest_login_and_reference_are_taken(
    dev: httpx.AsyncClient, owner_engine: AsyncEngine, built: Built
) -> None:
    login, reference = "a" + "-b" * 19, "R" * 40  # 39 characters; 40 characters
    saved = await dev.patch("/api/me/profile", json={"github_login": login, "kecobo_number": reference})
    assert saved.status_code == 200, saved.text
    assert await stored(owner_engine, built.owner_id) == (login, reference, None)


async def test_a_login_typed_with_its_at_sign_is_saved_without_it(
    dev: httpx.AsyncClient, owner_engine: AsyncEngine, built: Built
) -> None:
    """The certificate prints ``GitHub @login``: a developer who types ``@octocat`` means ``octocat``."""
    saved = await dev.patch("/api/me/profile", json={"github_login": " @octocat "})
    assert saved.status_code == 200, saved.text
    assert saved.json()["github_login"] == "octocat"
    assert await stored(owner_engine, built.owner_id) == ("octocat", None, None)
    longest = "a" + "-b" * 19  # 39 characters: the @ is not counted
    assert (await dev.patch("/api/me/profile", json={"github_login": f"@{longest}"})).status_code == 200
    assert await stored(owner_engine, built.owner_id) == (longest, None, None)


async def test_the_certificate_says_self_reported_and_verify_never_shows_them(
    dev: httpx.AsyncClient, app_engine: AsyncEngine, built: Built
) -> None:
    path = f"/api/provenance/certificates/{built.cert_id}/certificate.pdf"
    plain = pdf_text((await dev.get(path)).content)
    assert "Self-reported references" not in plain  # none set: no row

    await dev.patch("/api/me/profile", json={"github_login": LOGIN, "kipi_number": KIPI})
    response = await dev.get(path)
    assert response.status_code == 200, response.text
    text_ = pdf_text(response.content)
    assert "Self-reported references" in text_
    assert f"GitHub @{LOGIN}" in text_
    assert f"KIPI {KIPI}" in text_
    assert "KECOBO" not in text_  # only the set ones
    assert text_.index("Owner") < text_.index("Self-reported references")

    await dev.patch("/api/me/profile", json={"kecobo_number": KECOBO})
    assert f"KECOBO {KECOBO}" in pdf_text((await dev.get(path)).content)

    async with make_client(app_engine, ip="127.0.7.2") as anonymous:
        public = await anonymous.get(f"/api/verify/{built.cert_id}")
    assert public.status_code == 200, public.text
    for value in (LOGIN, KECOBO, KIPI, "Self-reported", "github", "kecobo", "kipi"):
        assert value.lower() not in public.text.lower()


async def test_dismissing_the_ip_nudge_is_once_and_the_developers_own(
    dev: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, built: Built
) -> None:
    async def dismissed() -> datetime | None:
        async with owner_engine.connect() as conn:
            found: datetime | None = (
                await conn.execute(
                    text("SELECT ip_nudge_dismissed_at FROM developer_profiles WHERE user_id = :u"),
                    {"u": built.owner_id},
                )
            ).scalar_one()
        return found

    assert await dismissed() is None
    first = await dev.post("/api/me/profile/ip-nudge/dismiss")
    assert first.status_code == 204, first.text
    at = await dismissed()
    assert at is not None
    assert (await dev.post("/api/me/profile/ip-nudge/dismiss")).status_code == 204
    assert await dismissed() == at  # once, for good

    world = await tracker_world(owner_engine)  # an organisation member has no developer profile
    async with make_client(app_engine, ip="127.0.7.3") as member:
        await sign_in_as(member, app_engine, world.viewer, mfa_verified=False)
        assert (await member.post("/api/me/profile/ip-nudge/dismiss")).status_code == 404
