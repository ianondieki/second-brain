# REQ-ENG-09

- Task: P5 (stages 9–13, main path). Design: `REQ-ENG-01.md` ("P5 — tracker main path").
- Agent: impl-backend.

## Scope built in the prototype

The milestone sub-tracker on the signed agreement (start, submit: the developer's endorsement; accept or request
changes: the organisation's); `deliver` once every milestone is accepted; `accept_delivery` issues the acceptance
certificate; the organisation's signatory signs it and the developer countersigns (the second signature enters
PAYMENT_FINAL); the organisation (owner, admin, signatory or finance) records the final payment (KES, method,
reference, date not in the future); the developer confirms the amount received, only at the recorded amount (409
otherwise, nothing recorded), which closes the engagement and its tag. The platform never holds or moves money.

## Tests

`tests/integration/engagements/test_tracker_path.py`, `test_tracker_guards.py::test_a_payment_is_confirmed_only_at_the_recorded_amount`.

## After the prototype

Milestone payments, deemed acceptance, the handover checklist, amount mismatch -> DISPUTED (AC-TRACK-7), the IP record
and provenance event at CLOSED (AC-IP-8), the optional rating.
