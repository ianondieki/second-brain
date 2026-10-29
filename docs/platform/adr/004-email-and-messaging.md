# ADR-004: Email and messaging channels

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/06-feature-modules.md (6.10, 6.11), docs/spec/08-architecture-stack-data-model.md (Email / WhatsApp / Voice), docs/spec/02-existing-repo.md (notify.py port)
- Related: ADR-005 (wording models), ADR-008 (WhatsApp in Release 2), REQUIREMENTS.md notification matrix N01–N23

## Context

The platform sends transactional email (approval EM2, signatures, declines), broadcast digests (scout EM3, daily
EM7) and in-app notifications. The local tool used Gmail SMTP and Meta WhatsApp Cloud API. Real email requires
sender-domain DNS (G7). CI must never reach a real provider (AC-SEC-5).

## Decision

1. **`EmailProvider` interface** with two adapters: `PostmarkProvider` (transactional stream for N-events, broadcast stream for digests; bounce/complaint webhooks feed `email_suppressions`) and `MailpitProvider`/SMTP sink used whenever `APP_ENV in (dev, test, staging)`. Gmail SMTP is dropped from the platform (kept in the local companion only). Amazon SES is the documented fallback adapter if Postmark onboarding fails; switching is an adapter change plus DNS.
2. **Test mode routes everything to Mailpit**; every test that asserts an email reads the Mailpit API. No path in `pr.yml`, `main.yml` or `make check` may reach a real provider.
3. **Templates**: EM1–EM8 as Jinja2 with `{{ }}` placeholders, i18n keys (`locales/en.json`, `locales/sw.json`), single CTA, plain-text part, footer (engagement ref · Manage notifications · Help · Nairobi, Kenya). Digest and reminder bodies are rendered by code from fixed templates with escaped fields; quoted developer text is defanged (`example[.]com`) and never auto-linkable (AC-MAIL-5). Transactional events marked 🔒 (approval, signatures, decline, dispute, termination) cannot be muted; all others have per-kind preferences. Notifications without a numbered template use one fixed "status change" layout (subject, one sentence, one CTA, footer); no new numbered templates are added without a spec change.
4. **Delivery ledger**: `notification_deliveries(user_id, kind, local_date, channel)` unique constraint enforces ≤1 daily reminder per user per channel; retries ≤3 with transient/permanent classification carried over from `reminder/notify.py` `DeliveryError(transient)` (AC-MAIL-3). EM2 uses a dedupe key on `(engagement_id, kind=EM2)` (AC-MAIL-1).
5. **In-app notifications** are always on (`in_app_notifications`), read from the bell; digests link only to authenticated pages and nothing changes state on GET.
6. **WhatsApp** (Meta Cloud API utility templates en/sw, opt-in, quiet hours 21:00–07:00 EAT, queued) is Release 2; the port of `build_whatsapp_template`/`send_whatsapp`/HMAC webhook check lands behind a feature flag with AC-MAIL-4 as its test. Voice (TTS/STT) is Release 2 and must not use edge-tts in production.
7. **Sender identity**: no real email leaves the platform before G7 signs SPF/DKIM/DMARC (`p=quarantine`). Org invitations follow the `docs/spec/06` 6.2 rules (aggregated, content-free, admin-approved, ≤1 per 30 days, ≤2 lifetime, role addresses only, RFC 8058 one-click unsubscribe, permanent suppression).

## Alternatives considered

- Keep Gmail SMTP: rejected; no bounce handling, sending limits, and shared credentials with a personal account.
- Amazon SES as primary: acceptable technically; Postmark chosen for simpler transactional/broadcast stream separation and bounce webhooks; SES stays the fallback adapter.
- Self-hosted MTA: rejected; deliverability and DMARC alignment cost more than the pilot budget.
- WhatsApp in Release 1: rejected; template approval, opt-in consent flows and quiet-hour queuing are not needed for the anchor-org pilot and would delay G8.

## Consequences

- Postmark account and sender domain are G7/vendor items; until then staging uses Mailpit and the human sees emails in the Mailpit UI.
- A single `EmailProvider` seam makes AC-DIR-1 ("zero emails to E0 orgs") and AC-SUB tests deterministic.
- Copy for EM1–EM8 is written by agents and tagged `[[COPY-REVIEW]]` for G2/G5 review.
