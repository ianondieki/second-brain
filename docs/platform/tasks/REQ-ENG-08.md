# REQ-ENG-08

- Task: P5 (stage 8). Design: `REQ-ENG-01.md` ("P5 — tracker main path").
- Agent: impl-backend.

## Scope built in the prototype

Agreement versions carry IP terms, the deemed-acceptance clause (0 = never), optional exclusivity and 1–20
milestones (deliverable, KES minor units, due date, review window); the party that did not draft the latest version
marks it final (the text's SHA-256 is frozen as the "PDF hash"); both parties sign it with the internal simple
e-signature behind a fresh TOTP step-up (the developer at D2, the organisation's signatory), each signature writing a
`doc.signed` audit event with the hash and step-up method; the second signature marks it signed and enters
IN_IMPLEMENTATION. Assignment and exclusive licence are refused by the internal e-signature (409, "sign outside the
platform"); `reopen_negotiation` returns to NEGOTIATION.

## Tests

`tests/integration/engagements/test_tracker_guards.py` (step-up, D2, assignment), `test_tracker_path.py`.

## After the prototype

PDF rendering, PAdES seal and RFC 3161 token on signatures, "Signed outside the platform" (upload and endorse), SMS
fallback, blocked document types, `test_signing.py` in full (AC-TRACK-10's remaining clauses).
