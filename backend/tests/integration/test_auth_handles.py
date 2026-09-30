"""REQ-AUTH-01 (docs/spec/06 6.1; THREAT_MODEL §5): signup gives each developer a random handle with nothing of their
display name or email address in it, of the one format, and draws again when the handle is taken. Until this fix the
handle was the display name slugged ("Achieng Otieno" → ``achieng-otieno-2b2356``); these tests fail against it.
What organisations see of it is in ``integration/engagements/test_handle_pseudonym.py``."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth import handles, service
from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.profiles.consents import consents_version
from bridge.seed.reference import seed_all
from tests.integration.api import make_client
from tests.integration.test_auth_flows import PASSWORD, link_token
from tests.name_tokens import leaked

SEED = 20260930
# Names as people write them: one word, several, hyphens and apostrophes, accents, Gĩkũyũ tildes, other scripts.
FIXED_NAMES = (
    "Achieng Otieno",
    "Achieng",
    "Wanjĩrũ Ngũgĩ",
    "Zoë O'Brien-Müller",
    "José María Kamau",
    "Łukasz Kiprono",
    "N'Golo Kanté",
    "Ōmondi Barasa",
    "李小龙",
    "Αλέξανδρος Mwangi",
    "Nyambura wa Kahiga",
    "  Kip  ",
)
SYLLABLES = "a chi eng ki ma ne tie wa nji rũ mu ga zö jo sé ła kasz nya mbu ra ké ba rö ke ny gĩ ta ya ho dhi am bo"


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


def random_names(count: int) -> list[str]:
    rng = random.Random(SEED)
    syllables = SYLLABLES.split()
    words = ["".join(rng.choice(syllables) for _ in range(rng.randint(2, 4))) for _ in range(count * 3)]
    separators = (" ", " ", "-", "'")
    names = []
    for i in range(count):
        parts = [w.capitalize() for w in words[i * 3 : i * 3 + rng.randint(1, 3)]]
        names.append(rng.choice(separators).join(parts))
    return names


def email_for(name: str) -> str:
    """An address whose local part repeats the name (as many do), at a unique domain."""
    local = ".".join(w for w in "".join(c if c.isascii() and c.isalnum() else " " for c in name).lower().split())
    return f"{local or 'me'}@u{uuid4().hex[:12]}.example.test"


async def create_developer(app_engine: AsyncEngine, name: str, email: str) -> UUID:
    account = service.NewAccount(
        email=email, display_name=name.strip(), locale="en", side="developer", org=None, consents={}, method="password"
    )
    async with create_session_factory(app_engine)() as db:
        user = await service.create_account(db, get_settings(), account, password_hash=None)
        assert user is not None
        await db.commit()
        return user.id


async def handle_of(owner_engine: AsyncEngine, user_id: UUID) -> str:
    async with owner_engine.connect() as conn:
        found = await conn.scalar(text("SELECT handle FROM developer_profiles WHERE user_id = :u"), {"u": user_id})
    return str(found)


def draws(values: list[str]) -> tuple[Callable[[], str], list[str]]:
    """A stand-in for ``handles.new_handle`` returning ``values`` in turn, and the list of what it returned."""
    given: list[str] = []
    source: Iterator[str] = iter(values)

    def draw() -> str:
        given.append(next(source))
        return given[-1]

    return draw, given


async def test_a_handle_has_nothing_of_the_name_or_email_over_many_names(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forty-two developers, twelve names as written and thirty drawn from syllables (accents, tildes, one to three
    words): every handle has the format, none holds a piece of the name or of the email's local part, and the handles
    are exactly what the seeded random source gives with no name at all, so they depend on nothing else."""
    monkeypatch.setattr(handles, "_rng", random.Random(SEED))
    names = [*FIXED_NAMES, *random_names(30)]
    found = []
    for name in names:
        email = email_for(name)
        handle = await handle_of(owner_engine, await create_developer(app_engine, name, email))
        assert handles.PATTERN.fullmatch(handle), (name, handle)
        assert leaked(handle.removeprefix(handles.PREFIX), name, email.split("@")[0]) == [], (name, handle)
        found.append(handle)
    replay = random.Random(SEED)
    monkeypatch.setattr(handles, "_rng", replay)
    assert found == [handles.new_handle() for _ in names]


async def test_signup_through_the_api_gives_a_random_handle(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """The route and the email link, with the operating system's random source (no stand-in)."""
    address = f"achieng.otieno.{uuid4().hex[:8]}@example.com"
    body = {
        "email": address,
        "password": PASSWORD,
        "display_name": "Achieng Otieno",
        "side": "developer",
        "accept_terms": True,
        "consents": {"reminders": True},
        "consents_version": consents_version(get_settings()),
    }
    async with make_client(app_engine) as client:
        assert (await client.post("/api/auth/signup", json=body)).status_code == 202
        consumed = await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
        assert consumed.status_code == 200
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT p.handle, u.display_name FROM developer_profiles p JOIN users u ON u.id = p.user_id"
                    " WHERE u.email = :e"
                ),
                {"e": address},
            )
        ).one()
    assert handles.PATTERN.fullmatch(row.handle)
    assert leaked(row.handle, row.display_name, address.split("@")[0]) == []


async def test_a_taken_handle_is_drawn_again(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unique constraint is case-insensitive (citext): the same handle in capitals is taken too."""
    taken = await handle_of(owner_engine, await create_developer(app_engine, "Achieng Otieno", email_for("a")))
    fresh = handles.new_handle()
    draw, given = draws([taken, taken.upper(), fresh])
    monkeypatch.setattr(handles, "new_handle", draw)
    second = await create_developer(app_engine, "Otieno Achieng", email_for("b"))
    assert await handle_of(owner_engine, second) == fresh
    assert given == [taken, taken.upper(), fresh]


async def test_signup_fails_closed_when_every_handle_drawn_is_taken(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = await handle_of(owner_engine, await create_developer(app_engine, "Achieng Otieno", email_for("c")))
    draw, given = draws([taken] * (service.HANDLE_ATTEMPTS + 1))
    monkeypatch.setattr(handles, "new_handle", draw)
    address = email_for("d")
    with pytest.raises(service.HandleUnavailable):
        await create_developer(app_engine, "Otieno", address)
    assert len(given) == service.HANDLE_ATTEMPTS
    async with owner_engine.connect() as conn:  # nothing was committed
        assert await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": address}) == 0


async def test_another_integrity_error_is_not_taken_for_a_clash(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A second profile for the same developer breaks the primary key, not the handle's constraint: it is raised."""
    user_id = await create_developer(app_engine, "Achieng Otieno", email_for("e"))
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=user_id)
        with pytest.raises(IntegrityError, match="pk_developer_profiles"):
            await service._add_developer_profile(db, user_id)
