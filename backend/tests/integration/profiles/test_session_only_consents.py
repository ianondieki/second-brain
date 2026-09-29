"""REQ-PROP-05 / REQ-CON-01: the settings API neither lists nor records the writing assistant's opt-in
(``tier2_llm_assistant``), which lasts one sign-in and is given from the proposal editor
(``bridge.proposals.assistant_router``). A settings row never opened a session, and a settings withdrawal would have
ended one: both are gone."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.proposals.helpers import Developers, rows, user_of


async def test_the_settings_api_does_not_list_the_assistant_opt_in(developers: Developers) -> None:
    client = await developers()
    listed = {c["purpose"] for c in (await client.get("/api/me/consents")).json()}
    assert "tier2_llm_assistant" not in listed
    assert {"marketing", "reminders", "profiling", "tier2_llm_moderation"} <= listed


async def test_the_settings_api_refuses_the_assistant_opt_in(developers: Developers, owner_engine: AsyncEngine) -> None:
    client = await developers()
    version = (await client.get("/api/consents")).json()["version"]
    for granted in (True, False):
        body = {"tier2_llm_assistant": {"granted": granted, "version": version}}
        refused = await client.put("/api/me/consents", json=body)
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "consent_session_only"
    bundled = {
        "marketing": {"granted": True, "version": version},
        "tier2_llm_assistant": {"granted": True, "version": version},
    }
    assert (await client.put("/api/me/consents", json=bundled)).status_code == 422  # nothing of the bundle is kept
    recorded = await rows(owner_engine, "SELECT purpose FROM consents WHERE user_id = :u", u=user_of(client))
    assert recorded == []
