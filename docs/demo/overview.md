# Wazo — the prototype at a glance (P18 and P19, D-52)

Wazo is the hosted developer ⇄ organisation platform in this repository: developers publish ideas with timestamped
evidence of what they submitted and when, organisations find and review them under an Evaluation NDA, and both sides
follow one tracker from first contact to a closed project. This page is the pitch's map of the prototype after the
P18 design roll-out ("fundable product": direction C, Editorial trust, with the kanga-cut lattice as the one East
African signature). Everything here runs on the seeded demo (`make demo`; README "Run the demo"), with no AI provider,
no money moving and no real email.

## What to show, in demo-story order

| Beat | Who | Screen | Screenshot |
|---|---|---|---|
| The promise | anyone | Landing: the headline, the live product visual, how it works in three steps, the proof story | `screenshots/p18/landing-light-1440.jpg`, `hero/landing-light.jpg` |
| First login | Amina (developer) | The three-step tour, skippable, remembered | `screenshots/00-first-login-tour-1440.jpg`, `screenshots/p18/tour-light-375.jpg` |
| What needs her | Amina | Home: four tiles, "Needs you" with the deadline and one action, recommendations with the reasons | `screenshots/01-dev-home-1440.jpg`, `hero/home-light.jpg` |
| What is moving | Amina | Discover: trending problems as cards with sources and why each trends; projects; the opportunity gap | `screenshots/02-discover-trending-1440.jpg`, `screenshots/p18/discover-light-1440.jpg` |
| Evidence | Amina, then anyone | The idea's certificate sheet with the seal and the QR to `/verify`; the public check, signed out | `screenshots/03-idea-certificate-1440.jpg`, `screenshots/04-verify-public-1440.jpg`, `hero/certificate-light.jpg` |
| Writing | Amina | The editor's three steps and the labelled writing assistant; the teaser checks (overlap in words, what it gives away) | `screenshots/05-editor-assistant-1440.jpg`, `screenshots/05b-editor-checks-1440.jpg`, `screenshots/p18/editor-1-light-1440.jpg` |
| The tracker | Amina | Whose turn, the five stages, the next actions, the agreement, signatures and history | `screenshots/06-dev-tracker-1440.jpg`, `hero/tracker-light.jpg` |
| Paying | Amina | Plan & billing, then the simulated M-Pesa checkout with the drawn handset | `screenshots/07-billing-checkout-1440.jpg`, `screenshots/p18/checkout-light-375.jpg` |
| Reading under NDA | Telco A's reviewer | The Inbox, the Evaluation NDA step, the full proposal marked with her name (light and dark) | `screenshots/08-org-inbox-nda-1440.jpg`, `screenshots/09-org-full-proposal-1440.jpg` |
| Asking for proposals | Telco A's reviewer | Problems: a Problem Brief posted with a budget band and a deadline, in review | `screenshots/09b-org-brief-posted-1440.jpg`, `screenshots/p19/org-problems-light-1440.jpg` |
| The scout | Telco A's owner | Scout matches and why each matched; the scout's settings | `screenshots/10-org-scout-matches-1440.jpg`, `screenshots/p18/org-scout-light-1440.jpg` |
| Taking a step | Telco A's owner | The organisation's tracker: the review starts; a question for Brian, the review waiting on his clock | `screenshots/11-org-tracker-step-1440.jpg`, `screenshots/11b-org-tracker-question-1440.jpg` |
| The staff console | staff admin, moderator | Research runs, claims, the moderation queue as calm dense tables; the Brief hidden until approved | `screenshots/12-admin-research-1440.jpg`, `screenshots/13-admin-moderation-1440.jpg`, `screenshots/13b-admin-moderation-brief-1440.jpg` |
| The other side of the question | Brian (developer) | The bell and the Notifications page; the answer; a hold with its resume day; Discover › Briefs and a proposal from the Brief | `screenshots/14b-dev-notifications-1440.jpg`, `screenshots/14c-dev-tracker-on-hold-1440.jpg`, `screenshots/14d-discover-briefs-1440.jpg` |
| A day later | — | Mailpit: the branded daily nudge beside the organisation digest | `screenshots/14-mailpit-reminders-1440.jpg`, `screenshots/p18/email-em7.jpg` |
| On a phone | Amina, Telco A | Home, the tracker, the Briefs and the Inbox at 375 px | `screenshots/15-dev-home-375.jpg`, `screenshots/16-dev-tracker-375.jpg`, `screenshots/18-discover-briefs-375.jpg`, `screenshots/17-org-inbox-375.jpg` |

The hero set (`docs/demo/hero/`, 1440 × 900, light and dark) holds the four showpiece screens for a deck or a
one-pager: the landing, Home, the tracker and the certificate.

## What the design stands on

- **Tokens** (`frontend/app/globals.css`, `docs/platform/design/p18-design-system.md`): paper, ink, one accent
  (`#1f5e49`), a flourish from the lattice's ochre, light and dark as two sets of steps, WCAG AA throughout.
- **Type**: Newsreader for the page's own titles and the wordmark, IBM Plex Sans for everything read, IBM Plex Mono for
  fingerprints and codes; self-hosted, instanced to the weights in use, the two above-the-fold faces preloaded.
- **The lattice**: a 6 px band on the top bar, the landing's frames, the certificate, the problem card and `/verify`;
  never behind text.
- **One primary action per screen**, at most five sections in a portal's navigation, at most two chips per card, 360 px
  first, every string in the locale files (English and Swahili), no UI library and no runtime CDN.
- **Feel**: the seal draws once, the celebration on a closed engagement, bottom sheets on phones, a short buzz under
  the thumb after a tap (haptics behind reduced motion), the first-login tour that arrives with the page.
- **Honesty**: "Demo data" and "Demo fallback" labels stay, small and muted; the marked page says what the mark does and
  does not do; no claim of protection anywhere.

## Measured (rounds 2–3, 2026-10-01; `design-scorecard.md` has the tables)

- Lighthouse mobile, light and dark, twelve main pages: performance 91–99, accessibility 100, CLS 0; LCP at or
  under 2.5 s on ten of them, 2.5–2.9 s on the landing's and the developer Home's first uncached visit (D-53).
- Strict axe: 0 violations on 60 screens × 4 variants; Playwright: the full suite and the demo story green on the
  compose stack; JS under 150 KB gzipped on every route.
- Every screen scored ≥ 4 of 5 by the art-director pass (hierarchy, typography, colour, spacing, clarity, delight)
  against Linear, Stripe, Mercury and Wise; `reviewer` PASS (round 11 over the roll-out's fixes, round 12 over the
  last ones) and `ux-reviewer` PASS (round 5) on the final build; the closed tracker's celebration and the tour are
  remembered without a layout shift on any path (CLS 0), pinned by tests that sample the DOM between tasks.

## Where things are

- Run it: README "Run the demo" (`make demo`, the demo logins, `make demo-totp`).
- Record it again: `docs/demo/README.md` (`make demo-walkthrough`: video in `docs/demo/video/`, screenshots 00–17;
  the same seven screens before P18 are kept in `docs/demo/screenshots/before-p18/` for the before-and-after).
- The 60-second cut: `docs/demo/video-script.md`.
- Every screen's score, states, interaction and axe result: `docs/demo/design-scorecard.md`; every screenshot
  at 1440 and 375 px, light and dark: `docs/demo/screenshots/p18/`.
- The design system and its decisions: `docs/platform/design/p18-design-system.md`, `docs/platform/DECISIONS-NEEDED.md`
  (D-52, D-53), the directions that were considered: `docs/demo/directions/`.
