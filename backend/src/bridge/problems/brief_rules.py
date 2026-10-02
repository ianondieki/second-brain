"""The plain-code rules of a Problem Brief (REQ-DIR-05; docs/spec/06 6.2, 6.5; docs/spec/04 principle 1).

- Who writes: the organisation's owner, admin, signatory or reviewer (revision 0002's ``_ORG_EDITOR``).
- Text: a Brief is public once approved, so its title, statement and affected group are cleaned to plain text, carry
  no contact details (the sanitiser's rule, ``sanitise.contact_codes``, in a Brief's words) and keep the ProblemCard's
  lengths (docs/spec/06 6.5: a statement of at most 120 words, counted as the research checks count them, within a
  1,200-character cap); title and statement are required. An error names the field and a code, never the refused text.
- State: what the organisation's list shows, from the Brief's own status and its problem's.
- Open: a Brief asks for proposals while it is published (not a draft, not closed) and its deadline is unset or
  today or later (Africa/Nairobi on the platform clock).
- Budget band: a code from ``config/matching/weights_v1.yaml``; a stored code the configuration no longer has shows
  no band (never a made-up label).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final

from bridge.errors import ApiError
from bridge.matching.config import Weights, get_weights
from bridge.matching.schemas import BudgetBandOut
from bridge.models.enums import BriefStatus, ModerationState, OrgRole, ProblemStatus
from bridge.problems.brief_schemas import BriefFacts, BriefState
from bridge.problems.research.checks import MAX_STATEMENT_WORDS
from bridge.problems.research.text import word_count
from bridge.proposals import sanitise
from bridge.proposals.sanitise import FieldError
from bridge.proposals.schemas import OrgRef

EDITORS: Final = (OrgRole.OWNER, OrgRole.ADMIN, OrgRole.SIGNATORY, OrgRole.REVIEWER)  # revision 0002's _ORG_EDITOR
MAX_LENGTHS: Final[Mapping[str, int]] = {"title": 90, "statement": 1200, "affected_group": 200}  # characters, cleaned
REQUIRED: Final = frozenset({"title", "statement"})

# [[COPY-REVIEW]] every sentence below: shown next to the field or as the refusal; never the refused text.
_PUBLIC = "a Brief is public once approved, and developers answer it with proposals."
MESSAGES: Final[Mapping[str, str]] = {
    "contains_url": f"Remove the web address: {_PUBLIC}",
    "contains_domain": f"Remove the website or domain name: {_PUBLIC}",
    "contains_email": f"Remove the email address: {_PUBLIC}",
    "contains_phone": f"Remove the phone number: {_PUBLIC}",
    "contains_payment_number": f"Remove the till or paybill number: {_PUBLIC}",
    "blank": "Write this part of the Brief.",
    "unknown_niche": "Choose a niche from the list.",
    "unknown_county": "Choose a county from the list.",
    "unknown_budget_band": "Choose a budget band from the list.",
    "deadline_past": "Choose today or a later date.",
}
TOO_LONG: Final = "Keep this to {limit} characters or fewer."
TOO_MANY_WORDS: Final = "Keep this to {limit} words or fewer."
INVALID: Final = "Some parts of the Brief need attention."


def error(field: str, code: str) -> FieldError:
    return FieldError(field, code, MESSAGES[code])


def text_errors(fields: Mapping[str, str | None]) -> tuple[dict[str, str | None], list[FieldError]]:
    """Plain-text copies of a Brief's text fields (blank becomes None) and their errors, field by field: contact
    details (checked raw and cleaned), a blank title or statement, more than ``MAX_LENGTHS`` characters, a statement
    of more than ``MAX_STATEMENT_WORDS`` words (``too_long`` either way, the message saying which)."""
    cleaned: dict[str, str | None] = {}
    errors: list[FieldError] = []
    for name, value in fields.items():
        plain = None if value is None else sanitise.plain_text(value) or None
        cleaned[name] = plain
        if value is not None:
            errors.extend(error(name, code) for code in sanitise.contact_codes(value))
        if plain is None:
            if name in REQUIRED:
                errors.append(error(name, "blank"))
        elif len(plain) > MAX_LENGTHS[name]:
            errors.append(FieldError(name, "too_long", TOO_LONG.format(limit=MAX_LENGTHS[name])))
        elif name == "statement" and word_count(plain) > MAX_STATEMENT_WORDS:
            errors.append(FieldError(name, "too_long", TOO_MANY_WORDS.format(limit=MAX_STATEMENT_WORDS)))
    return cleaned, errors


def brief_state(status: BriefStatus, problem_status: ProblemStatus, moderation: ModerationState) -> BriefState:
    """What the organisation's list shows: closed (by the organisation, or archived), rejected (by staff), published
    (on Discover: the problem published and clear) or in review (waiting for staff, or held)."""
    if status is BriefStatus.CLOSED or problem_status is ProblemStatus.ARCHIVED:
        return "closed"
    if problem_status is ProblemStatus.REJECTED or moderation is ModerationState.REJECTED:
        return "rejected"
    if (
        status is BriefStatus.PUBLISHED
        and problem_status is ProblemStatus.PUBLISHED
        and moderation is ModerationState.CLEAR
    ):
        return "published"
    return "in_review"


def band_out(code: str | None, weights: Weights) -> BudgetBandOut | None:
    """The band of a stored code; none for a code the configuration no longer has (never a made-up label)."""
    band = None if code is None else weights.band(code)
    return None if band is None else BudgetBandOut(code=band.code, label=band.label)


def is_open(status: BriefStatus, deadline: date | None, today: date) -> bool:
    """Whether the Brief still asks for proposals: published, and its deadline unset or not passed."""
    return status is BriefStatus.PUBLISHED and (deadline is None or deadline >= today)


def facts(
    org: OrgRef | None, budget_band: str | None, deadline: date | None, *, status: BriefStatus, today: date
) -> BriefFacts:
    return BriefFacts(
        org=org,
        budget_band=band_out(budget_band, get_weights()),
        deadline=deadline,
        open=is_open(status, deadline, today),
    )


def invalid(errors: Sequence[FieldError]) -> ApiError:
    body = [{"field": e.field, "code": e.code, "message": e.message} for e in errors]
    return ApiError(422, "invalid_brief", INVALID, errors=body)
