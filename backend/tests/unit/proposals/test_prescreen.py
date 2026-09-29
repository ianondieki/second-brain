"""REQ-PROP-02 / REQ-MOD-01 (AC-PROP-6, hold half): the rules pre-screen holds a teaser that names a directory
organisation negatively or describes a security vulnerability; an LLM screen may add reasons but never releases a
hold (``merge``). Tier-1 fields only; the classifier output carries labels, never text."""

from __future__ import annotations

import pytest

from bridge.proposals.prescreen import (
    NAMES_ORG_NEGATIVE,
    SECURITY_VULNERABILITY,
    RulesPreScreen,
    ScreenInput,
    ScreenResult,
    merge,
    org_aliases,
)

ORGS = ("Safaricom PLC", "Airtel Networks Kenya Limited", "Afya Sacco Society Ltd", "Kenya Women Microfinance Bank PLC")


async def screen(**fields: str) -> ScreenResult:
    return await RulesPreScreen().screen(ScreenInput(fields=fields, org_names=ORGS))


@pytest.mark.parametrize(
    ("legal_name", "aliases"),
    [
        ("Safaricom PLC", {"Safaricom PLC", "Safaricom"}),
        ("Airtel Networks Kenya Limited", {"Airtel Networks Kenya Limited", "Airtel Networks", "Airtel"}),
        ("Afya Sacco Society Ltd", {"Afya Sacco Society Ltd", "Afya Sacco"}),
        ("Kenya Women Microfinance Bank PLC", {"Kenya Women Microfinance Bank PLC", "Kenya Women Microfinance Bank"}),
        ("University of Nairobi", {"University of Nairobi"}),
    ],
)
def test_org_aliases(legal_name: str, aliases: set[str]) -> None:
    assert set(org_aliases(legal_name)) == aliases


@pytest.mark.parametrize(
    "summary",
    [
        "Safaricom overcharges farmers for every transfer.",
        "The Airtel agents cheat customers daily.",
        "AFYA SACCO is corrupt and hides losses.",
        "Unlike Safaricom PLC, which is a scam, we are honest.",
    ],
)
async def test_an_org_named_negatively_is_held(summary: str) -> None:
    result = await screen(summary=summary)
    assert result.hold
    assert result.reasons == (NAMES_ORG_NEGATIVE,)


@pytest.mark.parametrize(
    "summary",
    [
        "Works with Safaricom M-Pesa and Airtel Money.",
        "A scam alert service for SACCO members.",  # negative word, no directory org
        "Safaricom customers lose airtime. A scam is hard to spot.",  # different sentences
        "Farmers lose milk before chilling.",
    ],
)
async def test_neutral_mentions_are_not_held(summary: str) -> None:
    result = await screen(summary=summary)
    assert not result.hold
    assert result.reasons == ()


@pytest.mark.parametrize(
    "text",
    [
        "We found a vulnerability in the agent app.",
        "An SQL injection in the portal exposes balances.",
        "Exploit the USSD session to read any account.",
        "Their portal has a security vulnerability.",
        "The agent system was hacked last year.",
        "This bug is exploitable from any phone.",
        "A zero-day in the router firmware.",
        "CVE-2024-12345 affects the payment gateway.",
        "Bypass the OTP on the login page.",
        "A data breach exposed member records.",
        "Their security loophole lets anyone reset PINs.",
    ],
)
async def test_security_vulnerability_content_is_held(text: str) -> None:
    result = await screen(problem_statement=text)
    assert result.hold
    assert SECURITY_VULNERABILITY in result.reasons


@pytest.mark.parametrize(
    "text",
    [
        "Cash transfers for vulnerable households in Turkana.",
        "Climate vulnerability assessments for county planners.",
        "We hacked together a prototype over a weekend.",
        "Exploit market gaps in rural cold chains.",
        "A hackathon winner, now piloting with two SACCOs.",
        "The contract was breached by neither party.",
    ],
)
async def test_ordinary_development_language_is_not_held(text: str) -> None:
    result = await screen(summary=text)
    assert result.reasons == ()


async def test_both_reasons_and_labels_only_in_the_classifier() -> None:
    result = await screen(
        title="Safaricom is useless", summary="A vulnerability in Safaricom lets attackers drain wallets."
    )
    assert result.reasons == (NAMES_ORG_NEGATIVE, SECURITY_VULNERABILITY)
    assert result.classifier == {
        "engine": "rules",
        "version": "1",
        "labels": [NAMES_ORG_NEGATIVE, SECURITY_VULNERABILITY],
        "fields": ["summary", "title"],
    }
    assert "Safaricom" not in str(result.classifier)


def test_an_llm_screen_adds_reasons_but_never_releases_a_hold() -> None:
    rules = ScreenResult(reasons=(SECURITY_VULNERABILITY,), hold=True, classifier={"engine": "rules"})
    llm = ScreenResult(reasons=("spam",), hold=False, classifier={"engine": "llm"})
    merged = merge(rules, llm)
    assert merged.hold
    assert merged.reasons == (SECURITY_VULNERABILITY, "spam")
    assert merge(llm).hold is False
    assert merge().reasons == ()
