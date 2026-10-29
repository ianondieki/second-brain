# Phase 1 auth UI — design plan (T1.9, REQ-AUTH-01)

Written by the orchestrator with the `frontend-design` skill before any UI code. Brand, name, logo and palette are
placeholders until G5 (GATES.md): every colour and radius below is a CSS variable in `frontend/app/globals.css`, so
G5 is a token swap, not a redesign. Copy is `[[COPY-REVIEW]]` and lives only in `frontend/locales/{en,sw}.json`.

## Subject, audience, job

- Subject: a Kenyan platform where local developers publish solutions to real problems and organisations (telcos,
  SACCOs, universities, counties, NGOs) review them under NDA and agree next steps, with one shared tracker.
- Audience for these screens: a developer on a mid-range Android phone on mobile data, and an organisation's
  product lead on a laptop. Both need to trust the site with an idea or a company account within one screen.
- Job: get a person into the right side (developer or organisation) with a verified email, and get organisation
  owners onto two-step sign-in, with nothing in the way.

## Token system

Colour (cool, calm, local; deliberately not cream + terracotta, not SaaS blue):

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F5F7F3` | page background: cool, faintly green-grey paper |
| `--ink` | `#16232F` | text and icons (contrast 14.8:1 on paper) |
| `--ink-soft` | `#4A5866` | secondary text (6.8:1) |
| `--jacaranda` | `#5B3E96` | the one accent: primary buttons, focus ring, the bridge line (7.6:1 on paper; white on it 8.2:1); Nairobi's jacaranda bloom, a local reference that is nobody's logo |
| `--jacaranda-wash` | `#ECE6F6` | selected radio row, info notice background |
| `--line` | `#C9D1C8` | hairlines and dividers; input borders use `--ink-soft` for 3:1 non-text contrast |
| `--ok` | `#1F6B47` | success text/icons, 6.0:1 (always with an icon and words) |
| `--error` | `#A8241B` | error text/icons, 6.6:1 (always with an icon and words) |

Radius: `--radius-control: 10px` for inputs and buttons, `--radius-panel: 16px` for the one side panel; nothing
else is rounded. No shadows except the focus ring (`2px` jacaranda outline, `2px` offset).

Type: one system font stack (docs/spec/07 item 5: no web fonts), `system-ui, -apple-system, "Segoe UI", Roboto,
"Noto Sans", sans-serif`. Scale (1.25 ratio, 16 px base): 14 / 16 / 20 / 25 / 31 / 39. Headings 600 weight with
`-0.01em` tracking; body 400 at line-height 1.6; codes (TOTP, recovery codes) use `font-variant-numeric:
tabular-nums` and letter-spacing 0.12em, not a monospace face. Sentence case everywhere, no all-caps labels,
no eyebrow labels, no arrows appended to button text.

Layout: mobile first at 360 px. One column, left-aligned, 16 px gutters, form width max 28 rem.

```
360 px (all auth screens)          >= 1024 px (auth screens)
+----------------------+           +------------------------------+------------------+
| Bridge (working name)|           | Bridge (working name)        |                  |
|                      |           |                              |   the bridge     |
| Heading              |           | Heading                      |   line (SVG)     |
| one sentence         |           | one sentence                 |                  |
| [fields...........]  |           | [fields...........]          |  3 plain facts   |
| [Primary action....] |           | [Primary action]             |  about how it    |
| secondary text link  |           | secondary text link          |  works           |
+----------------------+           +------------------------------+------------------+
```

The right-hand panel (desktop only, `aria-hidden` decoration plus real text) holds the page's one memorable
element: **the bridge line**, a single jacaranda stroke that runs from a small "Developer" node to an
"Organisation" node through four stage ticks (the tracker the two sides will share). On the landing page it draws
itself once on load (stroke-dashoffset, 900 ms); with `prefers-reduced-motion` it is simply drawn. It is the only
motion on the site in Phase 1.

## Principles

1. One primary action per screen, marked `data-primary` (AC-UX-2 is asserted from Phase 7; mark it now).
2. The side choice (developer / organisation) is the first decision on signup, as a two-option radio group of full-
   width rows (44 px+ touch targets), not two cards.
3. Consents are separate, unticked checkboxes under "Optional: what we may send you"; the terms checkbox is the only
   required one and links to the terms placeholder (`/legal/terms`, `[[LEGAL-PLACEHOLDER:tos]]`).
4. Errors say what happened and how to fix it, next to the field (`aria-describedby`), plus a summary at the top
   for server errors (`role="alert"`). No apologies.
5. Honest copy only (docs/spec/04 4.2): no "protect your idea", "theft-proof", "secure your IP".
6. Status is icon + text + colour. Focus is never hidden under a sticky bar. OTP inputs accept paste and use
   `inputmode="numeric" autocomplete="one-time-code"`.
7. English first; every string is a key in `locales/en.json` with the same key in `locales/sw.json`
   (draft Swahili tagged `[[SW-REVIEW]]`, goes live after G5). No string concatenation; 30% expansion room.

## Screens

| Route | Primary action | Notes |
|---|---|---|
| `/` | Create an account | Headline about the two sides and the shared tracker; secondary "Log in" link; bridge line draws once |
| `/signup` | Create account | Side radio, name, email, password (show/hide toggle, 12+ characters hint), organisation name + type (only when organisation), optional consents, terms |
| `/signup/check-email` | (none: one sentence + "Send the link again" secondary) | Also used after "Email me a sign-in link" |
| `/login` | Log in | Email + password; secondary action "Email me a sign-in link" (a text button) |
| `/auth/link` | (automatic) | Reads `#token`, posts it, then routes to `/auth/mfa` or the home for the user's side; expired link shows a way to ask for a new one |
| `/auth/mfa` | Continue | 6-digit code; "Use a recovery code" toggles the input |
| `/settings/security` | Turn on two-step sign-in | Ordered steps (`<ol>`, `aria-current="step"`): scan QR or copy the key; enter a code; save 10 recovery codes (shown once, copy/download) |
| `/dev`, `/org` | one action each | Phase 1 placeholders: greeting, two-step sign-in status, sign out in the top bar; org home tells an owner without TOTP to turn it on (primary action) |
