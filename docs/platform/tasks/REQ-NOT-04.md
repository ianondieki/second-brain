# REQ-NOT-04

- Task: P5 (EM2). Agent: impl-backend.
- Files: `bridge/notifications/em2.py`, `bridge/notifications/templates/em2_subject.txt.j2`, `em2.txt.j2`,
  `em2.html.j2`; sent by `bridge/engagements/notify.py` from the `engagements.notify` job
  (`bridge/jobs/notifications.py`).

## Scope built in the prototype

Entering INTEREST_CONFIRMED (the signatory's approval, or the developer's acceptance at stage 0) sends EM2 to the
developer's verified address exactly once per engagement (dedupe key `em2:<engagement>`; the job is queued in the
command's transaction and is idempotent), through the configured provider (Mailpit in dev), within the worker's
latency. Spec copy verbatim in plain text and HTML (one CTA, the engagement ref and "Manage notifications · Help ·
Nairobi, Kenya" in the footer): "will contact you shortly to agree on pursuing the project", the named contact (name,
role, channel), the contact-by date, "not a contract or a commitment to buy", the disclosure record, a computed
`tier2_status` (named viewers under NDA; shared but not opened, `[[COPY-REVIEW]]`; not shared yet), and the
public-entity sentence. The templates pass the copy-lint. An in-app notification (N04) goes with it.

## Tests

`tests/unit/notifications/test_em2.py`, `tests/integration/engagements/test_em2_contact.py`,
`test_tracker_branches.py::test_stage_0_the_developer_accepts_an_organisations_interest`.

## After the prototype

i18n keys and the Swahili version (G5), EM4–EM6 and EM8, the full dispatch with preferences (REQ-NOT-03).
