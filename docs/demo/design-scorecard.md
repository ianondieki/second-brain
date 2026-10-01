# Design scorecard (P18 roll-out; D-52)

One row per screen, scored 1–5 by the art-director pass against Linear, Stripe, Mercury and Wise on hierarchy (H),
typography (T), colour (C), spacing (S), clarity (Cl) and delight (D). Anything under 4 was reworked and
re-screenshotted before the row was written. "axe" is the strict pass (every impact) over the four variants (1440 and
375 px, light and dark) from `frontend/demo/design-shots.spec.ts`; "states" lists the states checked; "interaction"
covers the keyboard path, focus ring, hover and press, reduced motion on and off, and ≥ 44 px targets on phones.
Screenshots: `docs/demo/screenshots/p18/<name>-<theme>-<width>.jpg`; the strict axe results of the last full run are in `docs/demo/axe-p18.json` (48 shots, 0 violations on 2026-10-01).

| Screen | Shots | H | T | C | S | Cl | D | axe | states | interaction | ux-reviewer | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Landing | `landing` | 5 | 5 | 4 | 4 | 5 | 4 | 0 | static; long title at 375 | keyboard, focus, hover, motion | round 1 fixed (heading order, icon tiles, approved wording, footer targets) | two-line headline; framed product visual; demo badge |
| Developer Home | `home` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | needs-you, none waiting, no engagements (empty), no deadline | card links, focus ring on card | round 1 fixed (deadline order and ownership, section headers, demo badge) | stat tiles; cards as links; real data: `home-*` |
| Tracker | `tracker` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | current, both owe, ended (fixtures; unit tests) | actions, tabs, dialogs | round 1 fixed (names once, actions first on phones) | timeline as the one progress indicator; real data: `tracker-*` |
| Certificate (idea page) | `certificate` | 5 | 5 | 4 | 4 | 5 | 5 | 0 | timestamped, pending (unit); print | print, links | round 1 fixed (BLOCKER: dark-mode QR; id never breaks; Nairobi time) | the showpiece sheet; real data: `certificate-*` |
| Log in | `login`, `login-error` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | error (refused), busy, magic-link sending | tab order, focus, Enter submits | round 1: CHANGES_REQUIRED, every finding fixed; round 2 pending | card on paper; seal and three steps beside it |
| Sign up | `signup`, `signup-org` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | organisation fields, consents failed (retry), errors | radio cards, checkboxes 44 px | round 1 fixed; round 2 pending | |
| Check your email | `check-email` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | resent (success), error, no remembered address | one secondary action | round 1 fixed; round 2 pending | waiting drawing |
| Sign-in link | `link-failed` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | checking (waiting drawing), failed, interrupted, no password | | round 1 fixed; round 2 pending | |
| Two-step | `two-step`, `two-step-recovery` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | app code, recovery code, invalid code | large code field, 44 px switch | round 1 fixed; round 2 pending | |
| First-login tour | `tour` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | step 1–3, skip, done, remembered (unit + e2e/tour.spec.ts) | non-modal, 44 px buttons, rises once (reduced motion: in place) | round 2 pending | three steps per side; above the tab bar on phones |
| My ideas | `ideas` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | draft, held for review, published, unpublished changes, untitled (unit); empty (unit) | card links, focus ring on the card, 44 px New idea | round 2 pending | cards in a grid; heading order fixed (h2 under the title, h3 under Home's section) |
| Idea editor | `editor-1`, `editor-2`, `editor-3` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | saving, saved, not saved with retry (unit); field errors; required fields on publish; confidential notice; files; review counts and attestations | steps are buttons with aria-current; Continue first on phones; 44 px targets | round 2 pending | numbered timeline stepper; one flat card per group; eye and spark on the section headings |
| Writing assistant | `editor-consent`, `editor-assistant` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | consent dialog (API wording verbatim); demo fallback (no model); suggestion with Now, Suggested, Use this and Undo (unit); every refusal (unit) | modal focus trap, Escape is Not now, focus moves to the answer heading | round 2 pending | the answer lives in the editor's panel; viewport shot for the dialog |
