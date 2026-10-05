"""The demo dataset of ``python -m bridge.seed --demo`` (P9 ``make demo``; REQ-FND-02, REQ-DIR-02).

Fictional people and fixture organisations for local demos only. Every organisation name ends in "(fixture)" and every
address is at a reserved ``.example`` domain, so nothing here names or reaches a real person or organisation. The
proposals, problems and tags are fixture content, not product copy.

Credentials are fixed and public on purpose, so the owner can sign in during a demo: one password for every demo
account (``DEMO_PASSWORD``) and a TOTP secret derived from each address (``totp_secret``), which
``python -m bridge.demo totp`` turns into the current code. They are safe only because the demo seed and the helper
refuse to run outside ``APP_ENV`` dev and test (``bridge.seed.demo.demo_refusal``): a staging or production database
never holds these accounts.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Final

from bridge.models.enums import (
    DevVerification,
    EngagementState,
    IpTerms,
    OrgKind,
    OrgRole,
    OrgVerification,
    ProposalAsk,
    ProposalMaturity,
    StaffRole,
)

# Dev-only demo credentials (README "Run the demo"); refused outside APP_ENV dev and test.
DEMO_PASSWORD: Final = "bridge-demo-2026"  # noqa: S105 - public on purpose (dev and test only)
# Where the password is documented; the commands point here instead of printing it (CodeQL clear-text logging).
DEMO_LOGINS_DOC: Final = 'README.md, "Run the demo" → Demo logins'
TOTP_LABEL: Final = "bridge-demo-totp-v1"


def totp_secret(email: str) -> str:
    """The fixed, public TOTP secret of a demo account: base32 of the first 20 bytes of SHA-256 over a label and the
    address (32 characters, as ``pyotp.random_base32(32)``). Dev and test only."""
    digest = hashlib.sha256(f"{TOTP_LABEL}|{email.strip().lower()}".encode()).digest()[:20]
    return base64.b32encode(digest).decode("ascii")


@dataclass(frozen=True, slots=True)
class DemoDeveloper:
    email: str
    display_name: str
    level: DevVerification  # D1 through the phone flow (fake SMS); D2 set by the owner role (no API path yet)
    phone: str  # a fictional Kenyan mobile for the D1 flow; the fake SMS provider never sends it anywhere


@dataclass(frozen=True, slots=True)
class DemoSeat:
    email: str
    display_name: str
    roles: tuple[OrgRole, ...]


@dataclass(frozen=True, slots=True)
class DemoStaff:
    """A platform staff account (docs/spec/03). ``staff_role`` has no application path: the owner role sets it, as
    staff would, with ``demo_account`` (D-37: a demo staff admin's research calls may go to a free provider)."""

    email: str
    display_name: str
    role: StaffRole


@dataclass(frozen=True, slots=True)
class DemoOrg:
    legal_name: str
    slug: str  # organisations without an owner (E0) only; signed-up ones get a generated slug
    kind: OrgKind
    verification: OrgVerification
    domain: str | None  # the verified domain (E1, E2); None for E0
    niche: str  # niche slug (backend/seed/reference.yaml)
    county: str  # ISO 3166-2:KE code
    owner: DemoSeat | None  # signs the organisation up (owner and admin); None for E0
    seats: tuple[DemoSeat, ...] = ()


@dataclass(frozen=True, slots=True)
class DemoProblem:
    title: str
    statement: str


@dataclass(frozen=True, slots=True)
class DemoProposal:
    key: str
    owner: str  # the developer's address
    title: str
    niche: str
    county: str | None
    maturity: ProposalMaturity
    ask: ProposalAsk
    problem_statement: str
    impact_claims: str
    summary: str
    approach: str  # Tier 2 from here on
    architecture: str
    pricing: str
    links: tuple[str, ...] = ()
    new_problem: DemoProblem | None = None
    links_problem_of: str | None = None  # another proposal's key: link the problem it described
    pitch_to: tuple[str, ...] = field(default=())  # organisation legal names


@dataclass(frozen=True, slots=True)
class DemoMilestone:
    deliverable: str
    amount_kes_minor: int  # KES in cents
    due_in_days: int  # from the day the terms are proposed (the app clock)


@dataclass(frozen=True, slots=True)
class DemoEngagement:
    """An engagement opened by a Pitch to an E2 fixture, driven along the main path through the tracker API until it
    reaches ``target``. Terms and the payment reference are used only when the path gets that far."""

    proposal: str  # proposal key
    org: str  # organisation legal name
    target: EngagementState
    ip_terms: IpTerms = IpTerms.NON_EXCLUSIVE_LICENCE
    deemed_acceptance_days: int = 10
    milestones: tuple[DemoMilestone, ...] = ()
    payment_reference: str = "DEMO-PAYMENT-0001"


@dataclass(frozen=True, slots=True)
class DemoMessage:
    who: str  # "developer" (the proposal's owner) or an organisation role (OrgRole value): the seat holding it writes
    body: str  # plain text; never contact details or links (refused before first contact, D-57 (8))


@dataclass(frozen=True, slots=True)
class DemoThread:
    """Messages on an engagement's thread (P21; REQ-ENG-11), each posted in order through the API by its writer."""

    proposal: str  # proposal key
    org: str  # organisation legal name
    messages: tuple[DemoMessage, ...]


@dataclass(frozen=True, slots=True)
class DemoSavedSearch:
    """A developer's saved Discover search (P21; REQ-PERS-03), saved through the API with alerts on."""

    owner: str  # the developer's address
    name: str
    view: str  # "problems" or "briefs"
    niche: str | None = None  # niche slug
    county: str | None = None  # ISO 3166-2:KE code
    words: str | None = None


AMINA = DemoDeveloper("amina@developers.example", "Amina Wanjiru", DevVerification.D2, "+254700000101")
BRIAN = DemoDeveloper("brian@developers.example", "Brian Otieno", DevVerification.D1, "+254700000102")
DEVELOPERS: Final = (AMINA, BRIAN)


def _seat(domain: str, local: str, name: str, *roles: OrgRole) -> DemoSeat:
    return DemoSeat(f"{local}@{domain}", name, roles)


TELCO_A = DemoOrg(
    legal_name="Telco A (fixture)",
    slug="telco-a-fixture",
    kind=OrgKind.COMPANY,
    verification=OrgVerification.E2,
    domain="telco-a.example",
    niche="networks-telecommunications",
    county="KE-30",
    owner=_seat("telco-a.example", "owner", "Grace Mwangi", OrgRole.OWNER, OrgRole.ADMIN),
    seats=(
        _seat("telco-a.example", "signatory", "Peter Kamau", OrgRole.SIGNATORY),
        _seat("telco-a.example", "reviewer", "Rita Njeri", OrgRole.REVIEWER),
        _seat("telco-a.example", "finance", "Faith Achieng", OrgRole.FINANCE),
    ),
)
SACCO_B = DemoOrg(
    legal_name="SACCO B (fixture)",
    slug="sacco-b-fixture",
    kind=OrgKind.SACCO_MFI,
    verification=OrgVerification.E2,
    domain="sacco-b.example",
    niche="microfinance-saccos",
    county="KE-22",
    owner=_seat("sacco-b.example", "owner", "David Kiprono", OrgRole.OWNER, OrgRole.ADMIN),
    seats=(
        _seat("sacco-b.example", "signatory", "Mercy Wambui", OrgRole.SIGNATORY),
        _seat("sacco-b.example", "reviewer", "Samuel Mutua", OrgRole.REVIEWER),
        _seat("sacco-b.example", "finance", "Joyce Chebet", OrgRole.FINANCE),
    ),
)
COUNTY_C = DemoOrg(
    legal_name="County Government of C (fixture)",  # contains "county government", as county names do
    slug="county-c-fixture",
    kind=OrgKind.COUNTY_GOVT,
    verification=OrgVerification.E1,
    domain="county-c.example",
    niche="county-government",
    county="KE-32",
    owner=_seat("county-c.example", "owner", "Hassan Abdi", OrgRole.OWNER, OrgRole.ADMIN),
)
NGO_D = DemoOrg(
    legal_name="NGO D (fixture)",
    slug="ngo-d-fixture",
    kind=OrgKind.NGO_PBO,
    verification=OrgVerification.UNCLAIMED,
    domain=None,
    niche="social-ngo",
    county="KE-30",
    owner=None,
)
ORGS: Final = (TELCO_A, SACCO_B, COUNTY_C, NGO_D)

# The staff admin who starts research runs and approves research cards (P11) and reads the claims queue (P15), and
# the staff moderator who decides the moderation queue (P15; bridge.seed.demo.queues seeds an item in each queue).
STAFF_ADMIN = DemoStaff("admin@staff.example", "Staff Admin (demo)", StaffRole.ADMIN)
STAFF_MODERATOR = DemoStaff("moderator@staff.example", "Staff Moderator (demo)", StaffRole.MODERATOR)
STAFF: Final = (STAFF_ADMIN, STAFF_MODERATOR)

P1 = DemoProposal(
    key="P1",
    owner=AMINA.email,
    title="Repayment nudges for SACCO members",
    niche="microfinance-saccos",
    county="KE-22",
    maturity=ProposalMaturity.PROTOTYPE,
    ask=ProposalAsk.PILOT,
    problem_statement=(
        "Members of small SACCOs often miss loan repayments because reminders arrive late or not at all, and loan"
        " officers chase arrears by phone one member at a time."
    ),
    impact_claims="A two-branch pilot aims to cut arrears older than 30 days by a fifth within one quarter.",
    summary=(
        "A reminder service that sends each member a short message a few days before a repayment is due, lets them"
        " confirm or ask for a new date by replying, and gives loan officers a daily list of who needs a call."
    ),
    approach=(
        "Repayment dates come from the SACCO's nightly core-banking export. A rules engine picks the nudge days per"
        " member (three days before, the due day, two days after) and sends through a bulk SMS gateway. Replies are"
        " parsed for YES or LATER with a date; officers get a call list ranked by days overdue and amount."
    ),
    architecture=(
        "One Python service and a Postgres database on a small virtual machine in Kenya; an SMS gateway adapter; a"
        " read-only import of the export file. No member data leaves the SACCO's tenancy."
    ),
    pricing="KES 25,000 setup per branch, then KES 4 per member per month. The pilot is free for 60 days.",
    links=("https://example.com/demo/repayment-nudges",),
    new_problem=DemoProblem(
        title="SACCO members miss loan repayments",
        statement=(
            "Small SACCOs lose income and staff time chasing late repayments; members say reminders come too late or"
            " not at all."
        ),
    ),
    pitch_to=(SACCO_B.legal_name,),
)
P2 = DemoProposal(
    key="P2",
    owner=AMINA.email,
    title="Fuel-level alerts for off-grid tower sites",
    niche="networks-telecommunications",
    county=None,
    maturity=ProposalMaturity.MVP,
    ask=ProposalAsk.LICENCE,
    problem_statement=(
        "Generators at off-grid tower sites run dry, or lose fuel, without anyone noticing until the site goes down,"
        " and refuelling trips are planned from guesswork."
    ),
    impact_claims="Early warnings could halve unplanned outages caused by empty tanks and cut wasted refuelling trips.",
    summary=(
        "A low-cost sensor kit reports each tank's level every hour and raises an alert when fuel drops faster than"
        " the generator burns it or falls below a refill threshold; a map shows which sites to refuel next."
    ),
    approach=(
        "An ultrasonic level sensor on the tank lid reports over LoRa to a site gateway, which forwards readings over"
        " the site's own backhaul. A burn-rate model per generator flags drops that the load does not explain."
    ),
    architecture="Sensor kit, site gateway, an MQTT broker and a small web dashboard with a refuelling map.",
    pricing="KES 18,000 per site kit; KES 1,500 per site per month for monitoring and alerts.",
    new_problem=DemoProblem(
        title="Tower sites go down when generators run dry",
        statement=(
            "Operators of off-grid tower sites learn about empty or drained fuel tanks only after the site stops"
            " working."
        ),
    ),
    pitch_to=(TELCO_A.legal_name,),
)
P3 = DemoProposal(
    key="P3",
    owner=BRIAN.email,
    title="Cashless market-fee collection for counties",
    niche="county-government",
    county="KE-32",
    maturity=ProposalMaturity.PROTOTYPE,
    ask=ProposalAsk.CO_BUILD,
    problem_statement=(
        "County market fees are collected in cash by hand, so traders get no receipt they can check and the revenue"
        " office cannot see what was collected until days later."
    ),
    impact_claims="Aims to raise recorded market-fee revenue and give every trader a receipt they can check.",
    summary=(
        "Traders pay the daily market fee from their phone and get a numbered receipt; collectors confirm payment with"
        " a scan; the revenue office sees collections by market as they happen."
    ),
    approach=(
        "Mobile-money payments to a county paybill with the stall number as the account; a collector app scans the"
        " stall's QR code and shows whether today's fee is paid; a nightly reconciliation against the paybill"
        " statement."
    ),
    architecture="Android collector app, a web dashboard for the revenue office, one API service and Postgres.",
    pricing="Co-build: KES 400,000 for a two-market pilot, then a licence per market.",
    new_problem=DemoProblem(
        title="Market fees leak in cash handling",
        statement=(
            "Counties cannot reconcile daily market fees collected in cash, and traders have no proof of payment."
        ),
    ),
    pitch_to=(COUNTY_C.legal_name, NGO_D.legal_name, TELCO_A.legal_name),
)
P4 = DemoProposal(
    key="P4",
    owner=BRIAN.email,
    title="USSD repayment reminders for feature phones",
    niche="microfinance-saccos",
    county=None,
    maturity=ProposalMaturity.IDEA,
    ask=ProposalAsk.PILOT,
    problem_statement=(
        "Many SACCO members use feature phones, so app-based reminders never reach them and they miss repayment dates."
    ),
    impact_claims="Reaches members without smartphones, who make up most of the arrears in rural branches.",
    summary=(
        "Members dial a short code to see their next repayment date and amount, and can opt in to a reminder the day"
        " before it is due."
    ),
    approach="A USSD menu backed by the SACCO's loan schedule, with an opt-in reminder list per member.",
    architecture="USSD gateway callbacks to one small service with a read-only copy of the loan schedule.",
    pricing="KES 60,000 setup; USSD session costs passed through at the gateway's rate.",
    links_problem_of="P1",
    pitch_to=(SACCO_B.legal_name,),
)
PROPOSALS: Final = (P1, P2, P3, P4)

# The tracker at a few stages (P5): P3 with Telco A stays SUBMITTED from its Pitch (the live walk-through), P4 with
# SACCO B is INTEREST_CONFIRMED (EM2 to Brian), P1 with SACCO B is in NEGOTIATION on the organisation's draft, and P2
# with Telco A has run the whole main path to CLOSED (D2 signs the agreement; the payment is recorded, never moved).
ENGAGEMENTS: Final = (
    DemoEngagement(proposal=P3.key, org=TELCO_A.legal_name, target=EngagementState.SUBMITTED),
    DemoEngagement(proposal=P4.key, org=SACCO_B.legal_name, target=EngagementState.INTEREST_CONFIRMED),
    DemoEngagement(
        proposal=P1.key,
        org=SACCO_B.legal_name,
        target=EngagementState.NEGOTIATION,
        milestones=(
            DemoMilestone("Two-branch pilot with the daily call list", 12_000_000, 45),
            DemoMilestone("Roll-out to every branch and handover", 18_000_000, 120),
        ),
    ),
    DemoEngagement(
        proposal=P2.key,
        org=TELCO_A.legal_name,
        target=EngagementState.CLOSED,
        ip_terms=IpTerms.NON_EXCLUSIVE_LICENCE,
        milestones=(
            DemoMilestone("Sensor kits and alerts at ten pilot sites", 9_000_000, 30),
            DemoMilestone("Refuelling map and monthly report", 6_000_000, 60),
        ),
        payment_reference="DEMO-MPESA-QK12AB34CD",
    ),
)

# P21's thread, on Amina's engagement with SACCO B (P1, in NEGOTIATION; CONTACT_MADE without FEATURE_DEALS_ENABLED):
# SACCO B's owner, its named contact, writes first and last, so Amina finds a reply waiting. Fixture text: short,
# plain, about the pilot, and free of contact details and links at every stage.
THREAD: Final = DemoThread(
    proposal=P1.key,
    org=SACCO_B.legal_name,
    messages=(
        DemoMessage(
            OrgRole.OWNER,
            "Thank you for the pilot plan. Our members asked whether the reminders can come in Kiswahili as well as"
            " English. Can the pilot do both?",
        ),
        DemoMessage(
            "developer",
            "Yes. Each member gets the reminders in the language they choose, and both pilot branches can start with"
            " English and Kiswahili.",
        ),
        DemoMessage(
            OrgRole.OWNER,
            "Good. Our loan officers would also like the daily call list ready before the branches open in the"
            " morning.",
        ),
    ),
)
# P21's saved search: Amina's Problems view of a niche she likes, which the seed gives problems (P1's, and the research
# card). No county: developer-reported problems and national research cards carry none, so a county would empty it.
SAVED_SEARCH: Final = DemoSavedSearch(
    owner=AMINA.email, name="Microfinance & SACCOs", view="problems", niche="microfinance-saccos"
)

# The certificate exported for the end-to-end tests (E2E_VERIFY_CERT_ID; python -m bridge.demo cert-id).
EXPORTED_PROPOSAL: Final = P1
# The Tier-2 view recorded so that the owner's "Who has seen this" is not empty (with FEATURE_TIER2_ENABLED only).
VIEWED: Final = (P1, SACCO_B, SACCO_B.seats[1])


def all_accounts() -> list[tuple[str, str, str]]:
    """Every demo login as (address, name, what it is), in the order the banner and the README list them."""
    accounts = [(dev.email, dev.display_name, f"developer, {dev.level.value.upper()}") for dev in DEVELOPERS]
    for org in ORGS:
        people = ([org.owner] if org.owner else []) + list(org.seats)
        for seat in people:
            roles = "+".join(role.value for role in seat.roles)
            accounts.append((seat.email, seat.display_name, f"{org.legal_name}: {roles}"))
    accounts.extend((staff.email, staff.display_name, f"platform staff: {staff.role.value}") for staff in STAFF)
    return accounts
