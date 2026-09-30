# The demo walkthrough

[[COPY-REVIEW]]

A three-minute tour of the seeded demo (`make demo`), and how to record it again. The recording is a Playwright script
that signs in through the real login and two-step screens, one person at a time, and walks the story below.

## Record it

The walkthrough changes the demo's data (Amina upgrades, Telco A accepts an NDA and starts a review, a moderation case
is decided, the clock moves a day), so start from a fresh demo each time:

1. `make demo-reset` (without make: `python infra/demo/demo.py reset --yes`).
2. `make demo-walkthrough` (on macOS and Linux `make demo-walkthrough DEMO_PY=python3`). It writes the Playwright
   variables (`python infra/demo/demo.py e2e-env`), then runs `frontend/demo/walkthrough.spec.ts` with its own config
   and moves the demo clock one day and sends the reminders on the way.
   Without make, from the repository folder: `python infra/demo/demo.py e2e-env`, then
   `cd frontend && npx playwright test -c demo/walkthrough.config.ts` (set `WALKTHROUGH_RUN_DEMO_CMDS=1` to include
   the clock and reminders commands; without it Mailpit shows the reminders of the demo's first day).
3. The video lands in `docs/demo/video/<test>/video.webm` (1280 × 720, not committed); the screenshots below are
   rewritten in `docs/demo/screenshots/`. `WALKTHROUGH_PAUSE_MS` sets the pause between steps (default 1200);
   `WALKTHROUGH_DEMO_REPO` names the checkout that started the demo, when you run the walkthrough from another one.

## Screenshots

| File | What it shows |
|---|---|
| [01-dev-home-1440.jpg](screenshots/01-dev-home-1440.jpg) | Amina's Home: what needs her, then problems recommended for her with the reasons |
| [02-discover-trending-1440.jpg](screenshots/02-discover-trending-1440.jpg) | Discover: trending problems with their sources and why they trend |
| [03-idea-certificate-1440.jpg](screenshots/03-idea-certificate-1440.jpg) | One of Amina's ideas: its timestamped certificate |
| [04-verify-public-1440.jpg](screenshots/04-verify-public-1440.jpg) | The public check of that certificate, signed out: the evidence, no name or title |
| [05-editor-assistant-1440.jpg](screenshots/05-editor-assistant-1440.jpg) | A new idea's first step with the writing assistant's labelled answer |
| [06-dev-tracker-1440.jpg](screenshots/06-dev-tracker-1440.jpg) | The tracker with SACCO B: whose turn it is, the five stages, the next actions |
| [07-billing-checkout-1440.jpg](screenshots/07-billing-checkout-1440.jpg) | The simulated M-Pesa checkout, confirmed |
| [08-org-inbox-nda-1440.jpg](screenshots/08-org-inbox-nda-1440.jpg) | Telco A's reviewer on Brian's proposal: the Evaluation NDA to accept |
| [09-org-full-proposal-1440.jpg](screenshots/09-org-full-proposal-1440.jpg) | The full proposal, marked for the person who opened it |
| [10-org-scout-matches-1440.jpg](screenshots/10-org-scout-matches-1440.jpg) | Telco A's Scout matches: what the scout found and why it matched |
| [11-org-tracker-step-1440.jpg](screenshots/11-org-tracker-step-1440.jpg) | Telco A takes its first step on Brian's tracker: the review starts |
| [12-admin-research-1440.jpg](screenshots/12-admin-research-1440.jpg) | The staff console's Research: a run and its result |
| [13-admin-moderation-1440.jpg](screenshots/13-admin-moderation-1440.jpg) | The oldest moderation case, ready to decide |
| [14-mailpit-reminders-1440.jpg](screenshots/14-mailpit-reminders-1440.jpg) | Mailpit a day later: the developer's new daily nudge, beside the weekly organisation digest sent on the demo's first day |
| [15-dev-home-375.jpg](screenshots/15-dev-home-375.jpg) | Amina's Home on a phone |
| [16-dev-tracker-375.jpg](screenshots/16-dev-tracker-375.jpg) | The SACCO B tracker on a phone |
| [17-org-inbox-375.jpg](screenshots/17-org-inbox-375.jpg) | Telco A's Inbox on a phone |

## The story (about three minutes)

Every login uses the password `bridge-demo-2026` and a code from `make demo-totp` (README, "Run the demo").

1. **Amina, developer** (`amina@developers.example`). Home shows what needs her now (her turn with SACCO B) and the
   problems recommended for her, each with how to pursue it and why it is there.
2. Discover: the problems trending now, with their sources; the Projects view; the Opportunity gap (rising problems
   with few proposals).
3. My ideas → "Repayment nudges for SACCO members": who has opened the full details (a SACCO B reviewer, under the
   NDA) and the idea's certificate.
4. Signed out, anyone can check that certificate on `/verify`: the fingerprint and the independent timestamp, never
   the title or the owner.
5. "New proposal": the first step of the editor. With an AI provider set, the writing assistant offers a suggestion
   she may use; without one (the default) it says there is no suggestion, labelled "Demo fallback". Nothing changes
   unless she uses a suggestion. The idea is not published.
6. Engagements → SACCO B: whose turn it is and what is due, the five stages, the draft agreement and its milestones,
   the signatures, and the History both parties share.
7. Plan & billing: the Free plan allows three published ideas and Amina has three; "Upgrade to Pro (monthly)" opens
   the simulated M-Pesa checkout, which confirms the payment. No money moves.
8. **Telco A's reviewer** (`reviewer@telco-a.example`). The Inbox has Brian's "Cashless market-fee collection for
   counties". She accepts the Evaluation NDA and reads the full proposal, marked with her name.
9. **Telco A's owner** (`owner@telco-a.example`). Inbox › Scout matches: the proposal the scout found and why it
   matched; the scout's settings and a preview of what it would match (not saved).
10. Engagements → Brian's proposal: it is Telco A's turn, so the owner starts the review; the tracker moves to Under
    review.
11. **Staff admin** (`admin@staff.example`). Research: a run over saved sources (without an AI provider it drafts no
    card and says so; the seeded example cards are already reviewed). Claims: County Government of C's claim, read
    only.
12. **Staff moderator** (`moderator@staff.example`). Moderation → the oldest case → approve it.
13. A day later (`make demo-clock DAYS=1`, then `make demo-reminders`): Mailpit shows Amina's new daily nudge. The
    organisation digest is weekly: Telco A's was sent on the demo's first day, and the command reports it as already
    sent.
14. The same screens on a phone: Amina's Home, the SACCO B tracker and Telco A's Inbox.
