"""Attachment scanning behind one interface (docs/spec/06 6.1: attachments are malware-scanned before they are kept).

The prototype uses ``FakeScanner`` only (D-36: no ClamAV in the prototype, zero spend and 4 GB for ``make demo``). It
answers "infected" for the EICAR anti-virus test string and "clean" for everything else, so it proves nothing about
real files: it is refused outside ``APP_ENV`` dev and test (``scanner_from_settings`` fails closed), and a ClamAV
scanner returns to the plan after the prototype (``ATTACHMENT_SCANNER=clamav`` is refused until then).

The EICAR string is assembled at import from pieces, so no source file holds it whole (a workstation's anti-virus
would quarantine the checkout).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from bridge.config import ConfigurationError, Settings

EICAR: Final = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS" + b"-TEST-FILE!$H+H*"


class Verdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"


@dataclass(frozen=True, slots=True)
class ScanResult:
    verdict: Verdict
    signature: str | None = None


class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(self, data: bytes) -> ScanResult: ...


class FakeScanner:
    """Demo and test only: EICAR is infected, anything else clean."""

    @property
    def name(self) -> str:
        return "fake-demo"

    async def scan(self, data: bytes) -> ScanResult:
        if EICAR in data:
            return ScanResult(Verdict.INFECTED, "Eicar-Test-Signature")
        return ScanResult(Verdict.CLEAN)


def scanner_from_settings(settings: Settings) -> Scanner:
    if settings.attachment_scanner == "fake":
        if settings.app_env not in ("dev", "test"):
            raise ConfigurationError("the fake attachment scanner runs only in dev and test (ATTACHMENT_SCANNER)")
        return FakeScanner()
    raise ConfigurationError("ClamAV scanning returns after the prototype (D-36); set ATTACHMENT_SCANNER=fake in dev")
