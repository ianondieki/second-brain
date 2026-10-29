# REQ-ENG-07

- Task: P5 (stages 4–7, main path). Design: `REQ-ENG-01.md` ("P5 — tracker main path").
- Agent: impl-backend.

## Scope built in the prototype

`mark_contacted` (the organisation's endorsement of CONTACT_MADE) and `confirm_contact` (the developer's); `send_nda`
once both confirmed, issuing the platform mutual NDA (the seeded `mutual_nda` template under a cover naming the
engagement; text and hash reproducible at `GET .../documents/mutual_nda`); both parties sign it (step-up) and the
second signature enters NDA_SIGNED; `propose_terms` creates agreement versions (NEGOTIATION, each renewing the 7 BD
deadline). Deal steps are 403 while `FEATURE_DEALS_ENABLED` is false (AC-SEC-7).

## Tests

`tests/integration/engagements/test_tracker_path.py`, `test_tracker_guards.py`.

## After the prototype

The developer's auto-confirmation after 3 BD, a disputed first contact (back to stage 3), uploaded NDAs and the
waiver, the deal room (Tier 3), term sheets and exclusivity with siblings ON_HOLD (AC-TRACK-6).
