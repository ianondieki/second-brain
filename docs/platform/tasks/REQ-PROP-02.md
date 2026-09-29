# REQ-PROP-02

- Task: T2.3 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend
- Files owned: `bridge/proposals/sanitise.py`, `bridge/admin/moderation.py`, `bridge/admin/router.py` (moderation queue routes)
- Depends on: T2.1, T2.2.

## Scope

The Tier-1 sanitiser rejects (422 with the field and a plain reason) URLs, bare domains, email addresses, phone numbers (E.164, 07xx/01xx, spaced and dotted variants) and till/paybill patterns. A teaser naming a directory org negatively or describing a security vulnerability is held (`moderation_state=held`, a `moderation_cases` row) and returned by no public, list or search endpoint until a moderator approves it; vulnerability content is never made public. Regex and heuristics decide holds; the Haiku pre-screen (REQ-MOD-01) can add reasons but never releases a hold.

## Acceptance criteria and tests

AC-PROP-6 (`unit/proposals/test_sanitise.py`, `integration/proposals/test_holds.py`).

## Prototype P2 (T2.3 minimal, 2026-09-29): built

- `bridge/proposals/sanitise.py`: `plain_text` (HTML tags, script and style blocks and comments removed, entities
  decoded repeatedly, NFKC, invisible format and control characters removed, whitespace tidied), `contact_findings`
  (URLs and schemes such as `mailto:`/`tel:`, bare domains on a curated TLD list including `.co.ke`-style names and
  "name [dot] com" / "x dot co dot ke", email addresses including "jane [at] host", Kenyan 07xx/01xx/254/+254 mobiles
  and E.164 with "+", with spaces, dots, hyphens or brackets, M-Pesa till/paybill/buy-goods numbers of 5 to 7 digits),
  `check_field` (raw and plain text, so a link hidden in HTML is still refused; the summary's 150 words). Errors name the
  field and a plain `[[COPY-REVIEW]]` reason, never the offending text. Applied to the four Tier-1 text fields and a new
  Problem's title and statement on every save and again at publishing.
- Holds (with REQ-MOD-01): `bridge/proposals/prescreen.py` `RulesPreScreen` holds `security_vulnerability` (a
  vulnerability vocabulary: exploits, injection, XSS/CSRF, RCE, auth/OTP bypass, breaches, CVE ids, ...) and
  `names_real_org_negative` (a listed directory organisation, by legal name, name without its legal form, or brand
  before a sector word, in the same sentence as a negative term). A held teaser is `moderation_state = held` with a
  `moderation_cases` row in the publishing transaction; RLS, the teaser endpoint and every other reader return nothing
  until a moderator approves it (`integration/proposals/test_holds.py`, AC-PROP-6); the author keeps full view.
- Tests: `unit/proposals/test_sanitise.py`, `unit/proposals/test_prescreen.py`, `integration/proposals/test_holds.py`,
  `integration/proposals/test_drafts.py` (refusal on save).

## After prototype (rescheduled, not removed)

- Broader evasion forms (a spelled-out single-level "example dot com", social handles, numbers written in words),
  a curated vulnerability taxonomy and org-alias list reviewed with moderators, Swahili vocabulary for both rules.
- The Haiku pre-screen adds reasons through `merge` (never releases a hold); Tier-2 regex moderation (docs/spec/06 6.12).
