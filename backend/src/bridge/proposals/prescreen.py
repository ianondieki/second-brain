"""Moderation pre-screen of Tier-1 fields (REQ-MOD-01, REQ-PROP-02; docs/spec/06 6.3, 6.12).

A teaser or a developer's new Problem that names a directory organisation negatively (``names_real_org_negative``) or
describes a security vulnerability (``security_vulnerability``) is held for a moderator: the publish flow raises the
hold (``app_hold_proposal``; a new Problem is inserted held) and files the case (``app_open_moderation_case``). Regex
and heuristics decide holds (docs/spec/04 principle 1). The prototype runs ``RulesPreScreen`` only; the Haiku
pre-screen of REQ-MOD-01 plugs in later behind ``PreScreen`` and is combined with ``merge``: it can add reasons (spam,
defamation, false affiliation, third-party personal data, malicious links) but never releases a hold.

Only Tier-1 text is screened, and the classifier output holds labels and field names, never text or names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.proposals.sanitise import detection_skeleton

NAMES_ORG_NEGATIVE: Final = "names_real_org_negative"
SECURITY_VULNERABILITY: Final = "security_vulnerability"
RULES_VERSION: Final = "1"


@dataclass(frozen=True, slots=True)
class ScreenInput:
    fields: Mapping[str, str]  # Tier-1 field name -> plain text
    org_names: Sequence[str] = ()  # legal names of the listed directory organisations


@dataclass(frozen=True, slots=True)
class ScreenResult:
    reasons: tuple[str, ...] = ()
    hold: bool = False
    classifier: dict[str, Any] | None = field(default=None)


class PreScreen(Protocol):
    async def screen(self, item: ScreenInput) -> ScreenResult: ...


def merge(*results: ScreenResult) -> ScreenResult:
    """Reasons of every screen, in order; held when any screen holds (a later screen never releases a hold)."""
    reasons = tuple(dict.fromkeys(reason for result in results for reason in result.reasons))
    classifiers = [result.classifier for result in results if result.classifier is not None]
    classifier: dict[str, Any] | None = None
    if len(classifiers) == 1:
        classifier = classifiers[0]
    elif classifiers:
        classifier = {"screens": classifiers}
    return ScreenResult(reasons, any(result.hold for result in results), classifier)


# --- organisation names ----------------------------------------------------------------------------------------------

_LEGAL_SUFFIXES = frozenset({"plc", "limited", "ltd", "ltd.", "society", "kenya", "company", "co.", "group", "inc"})
# A brand is recognised alone ("Airtel" for "Airtel Networks") only before a sector word, and only when it is not a
# common word of Kenyan organisation names.
_SECTOR_WORDS = frozenset(
    {"networks", "telecommunications", "telecom", "internet", "microfinance", "bank", "sacco", "mobile", "money"}
)
_NOT_A_BRAND = frozenset({"kenya", "national", "county", "ministry", "university", "catholic", "united", "central"})


def org_aliases(legal_name: str) -> list[str]:
    """The names a teaser may use for an organisation: the legal name, without its legal form, and a brand name."""
    aliases = [legal_name]
    tokens = legal_name.split()
    while len(tokens) > 1 and tokens[-1].lower() in _LEGAL_SUFFIXES:
        tokens.pop()
    short = " ".join(tokens)
    if short != legal_name:
        aliases.append(short)
    brand = tokens[0]
    if (
        len(tokens) >= 2
        and tokens[1].lower() in _SECTOR_WORDS
        and len(brand) >= 5
        and brand.isalpha()
        and brand.lower() not in _NOT_A_BRAND
    ):
        aliases.append(brand)
    return aliases


_NEGATIVE = re.compile(
    r"\b(?:fraud(?:ulent|sters?)?|scam(?:s|mers?|ming)?|corrupt(?:ion|ed)?|steal(?:s|ing)?|stole(?:n)?|theft"
    r"|thie(?:f|ves)|cheat(?:s|ed|ing)?|rip(?:s|ped)?[\s-]?off|liars?|lying|incompetent|useless|terrible|awful"
    r"|worst|disgrace(?:ful)?|overcharg(?:e|es|ed|ing)|negligen(?:t|ce)|illegal(?:ly)?|criminals?|crooks?"
    r"|extort(?:s|ion|ing)?|brib(?:e|es|ery|ing)|dishonest|hides?\s+losses"
    r"|exploit(?:s|ing)?\s+(?:its\s+|their\s+)?(?:customers|users|farmers|members|staff|workers))\b",
    re.IGNORECASE,
)
# Security vocabulary in a technical context only: "vulnerable households", "climate vulnerability", "we hacked
# together a prototype" and "exploit market gaps" are ordinary development language, not vulnerability reports.
_TECH_TARGET = (
    r"(?:apps?|systems?|portals?|apis?|websites?|sites?|platforms?|networks?|servers?|firmware|software|devices?"
    r"|routers?|gateways?|logins?|databases?|ussd|sims?|pos|atms?|wallets?|sessions?|endpoints?|tills?|cards?|pins?"
    r"|otps?|accounts?|modems?|meters?)"
)
_VULNERABILITY = re.compile(
    rf"\b(?:(?:security\s+)vulnerabilit(?:y|ies)|vulnerabilit(?:y|ies)\s+(?:in|on|of)\s+(?:[\w-]+\s+){{0,4}}?{_TECH_TARGET}"
    rf"|exploit(?:s|ed|ing)?\s+(?:the\s+|a\s+|an\s+|their\s+|its\s+|this\s+)?(?:[\w-]+\s+){{0,2}}?"
    rf"(?:{_TECH_TARGET}|bugs?|flaws?|holes?)|exploitable|(?:zero|0)[\s-]?day|cve-\d{{4}}-\d{{3,}}"
    r"|sql\s*injection|sqli|xss|cross[\s-]site\s+(?:scripting|request\s+forgery)|csrf|remote\s+code\s+execution"
    r"|rce|privilege\s+escalation|(?:auth(?:entication)?|login|security|otp|2fa|mfa|pin|paywall|verification)\s+bypass"
    r"|bypass(?:es|ed|ing)?\s+(?:the\s+|their\s+|its\s+|any\s+)?(?:auth(?:entication)?|login|security|otp|2fa|mfa"
    r"|pins?|verification|paywall)|data\s+(?:breach|leak)(?:es|s)?|security\s+(?:hole|flaw|loophole|gap"
    r"|weakness|bug)s?|backdoors?|hackable|(?:was|were|been|got)\s+(?:hacked|compromised)|unpatched"
    rf"|{_TECH_TARGET}\s+(?:was|were|been|got)\s+breached"
    r"|leak(?:ed|s|ing)?\s+(?:\w+\s+)?(?:credentials|passwords|pins|records))\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"[.!?;\n]+")


def _org_pattern(org_names: Sequence[str]) -> re.Pattern[str] | None:
    aliases = sorted({alias for name in org_names for alias in org_aliases(name)}, key=len, reverse=True)
    if not aliases:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in aliases) + r")(?!\w)", re.IGNORECASE)


class RulesPreScreen:
    """Regex and heuristics (the prototype's pre-screen)."""

    async def screen(self, item: ScreenInput) -> ScreenResult:
        orgs = _org_pattern(item.org_names)
        hits: dict[str, set[str]] = {NAMES_ORG_NEGATIVE: set(), SECURITY_VULNERABILITY: set()}
        for name, raw in item.fields.items():
            value = detection_skeleton(raw, blank=" ")  # lookalike letters and fillers do not dodge a hold
            if _VULNERABILITY.search(value):
                hits[SECURITY_VULNERABILITY].add(name)
            if orgs is not None and any(
                orgs.search(sentence) and _NEGATIVE.search(sentence) for sentence in _SENTENCES.split(value)
            ):
                hits[NAMES_ORG_NEGATIVE].add(name)
        reasons = tuple(reason for reason, fields in hits.items() if fields)
        if not reasons:
            return ScreenResult()
        classifier = {
            "engine": "rules",
            "version": RULES_VERSION,
            "labels": list(reasons),
            "fields": sorted(set().union(*hits.values())),
        }
        return ScreenResult(reasons, True, classifier)


_LISTED_ORG_NAMES = text(
    "SELECT legal_name FROM organizations WHERE verification IN ('unclaimed', 'e1', 'e2') AND delisted_at IS NULL"
)


async def listed_org_names(db: AsyncSession) -> list[str]:
    """Legal names of the organisations in the directory (what "a directory org" means for the hold rule)."""
    return list((await db.execute(_LISTED_ORG_NAMES)).scalars().all())
