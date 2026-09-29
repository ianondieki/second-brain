# REQ-ENG-05

- Task: P5 (stages 1–3 of the main path). Design: `REQ-ENG-01.md` ("P5 — tracker main path").
- Agent: impl-backend.

## Scope built in the prototype

`SUBMITTED` (10 BD) -> `UNDER_REVIEW` (15 BD) by an owner, admin, signatory or reviewer; `approve` by the signatory
only, naming the contact person (an active member), channel and contact-by date (today to 5 BD ahead; the stage
deadline); the developer's verified email revealed to the named contact only (`GET .../contact`, audit-logged, 403
before INTEREST_CONFIRMED); `decline` with the organisation's reason codes: `ALREADY_IN_PROGRESS_INTERNALLY` needs the
internal start date and the attestation (in the chain, shown to the developer), `OTHER` 20–1000 characters (salted
digest in the chain, the text in the audit details and the developer's notification).

## Tests

`tests/integration/engagements/test_tracker_branches.py`, `test_em2_contact.py`, `test_tracker_guards.py`;
`tests/unit/engagements/test_state_machine.py` (contact-by and decline checks).

## After the prototype

Admin escalation at +3 BD, `EXPIRED (CONTACT_NOT_MADE)` at +10 BD and the other expiries (the SLA job),
`INFO_REQUESTED` pausing the clock, the responsiveness score, the verified phone in the reveal (schema need).
