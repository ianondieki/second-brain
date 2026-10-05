# Design scorecard (P18 roll-out; D-52)

One row per screen, scored 1–5 by the art-director pass against Linear, Stripe, Mercury and Wise on hierarchy (H),
typography (T), colour (C), spacing (S), clarity (Cl) and delight (D). Anything under 4 was reworked and
re-screenshotted before the row was written. "axe" is the strict pass (every impact) over the four variants (1440 and
375 px, light and dark) from `frontend/demo/design-shots.spec.ts`; "states" lists the states checked; "interaction"
covers the keyboard path, focus ring, hover and press, reduced motion on and off, and ≥ 44 px targets on phones.
Screenshots: `docs/demo/screenshots/p18/<name>-<theme>-<width>.jpg`; the strict axe results of the last full run are in `docs/demo/axe-p18.json` (48 shots, 0 violations on 2026-10-01).

| Screen | Shots | H | T | C | S | Cl | D | axe | states | interaction | ux-reviewer | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Landing | `landing` | 5 | 5 | 4 | 4 | 5 | 4 | 0 | static; long title at 375 | keyboard, focus, hover, motion | round 1 fixed (heading order, icon tiles, approved wording, footer targets) | two-line headline; framed product visual about 15 % larger at 1440 (the owner's nit: tighter backdrop, taller stage, larger type and seal); the Who-it-is-for cards wrap in list items so the grid no longer stretches their icon tiles; demo badge |
| Developer Home | `home` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | needs-you, none waiting, no engagements (empty), no deadline | card links, focus ring on card | round 1 fixed (deadline order and ownership, section headers, demo badge) | stat tiles; cards as links; real data: `home-*` |
| Tracker | `tracker` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | current, both owe, ended (fixtures; unit tests) | actions, tabs, dialogs; Actions stays mounted when nothing is left (its Done status keeps focus) | round 1 fixed (names once, actions first on phones); round 2 fixed (avatars on the wash on a field surface, due dates unbreakable, Since in Nairobi time, tab ring inset); round 3 PASS (reviewer round 11) | timeline as the one progress indicator; real data: `tracker-*` |
| Certificate (idea page) | `certificate` | 5 | 5 | 4 | 4 | 5 | 5 | 0 | timestamped, pending (unit); print | print, links | round 1 fixed (BLOCKER: dark-mode QR; id never breaks; Nairobi time) | the showpiece sheet; real data: `certificate-*` |
| Log in | `login`, `login-error` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | error (refused), busy, magic-link sending | tab order, focus, Enter submits | round 1: CHANGES_REQUIRED, every finding fixed; ux-reviewer PASS (round 5, the whole branch on the final build) | card on paper; seal and three steps beside it |
| Sign up | `signup`, `signup-org` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | organisation fields, consents failed (retry), errors | radio cards, checkboxes 44 px | round 1 fixed; ux-reviewer PASS (round 5, the whole branch on the final build) | |
| Check your email | `check-email` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | resent (success), error, no remembered address | one secondary action | round 1 fixed; ux-reviewer PASS (round 5, the whole branch on the final build) | waiting drawing |
| Sign-in link | `link-failed` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | checking (waiting drawing), failed, interrupted, no password | | round 1 fixed; ux-reviewer PASS (round 5, the whole branch on the final build) | |
| Two-step | `two-step`, `two-step-recovery` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | app code, recovery code, invalid code | large code field, 44 px switch | round 1 fixed; ux-reviewer PASS (round 5, the whole branch on the final build) | |
| First-login tour | `tour` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | step 1–3, skip, done, Escape, remembered in storage and a cookie, storage refusing the write (unit + e2e/tour.spec.ts) | non-modal; in the page's flow on phones (covers nothing), floating above the tab bar from 640 px with the page's end reserved; Escape inside it; focus back to the title; 44 px buttons | round 2 fixed (hid focused controls, no Escape, focus to body, CLS 0.38 → 0 via the cookie the server reads); round 3 fixed (Show the tour again unmarks the document, so the tour returns on a client-side visit home, not only after a reload) | signpost drawing; three steps per side; Help offers it again |
| My ideas | `ideas` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | draft, held for review, published, unpublished changes, untitled (unit); empty (unit) | card links, focus ring on the card, 44 px New idea | ux-reviewer PASS (round 5, the whole branch on the final build) | cards in a grid; heading order fixed (h2 under the title, h3 under Home's section) |
| Idea editor | `editor-1`, `editor-2`, `editor-3` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | saving, saved, not saved with retry (unit); field errors; required fields on publish; confidential notice; files; review counts and attestations | steps are buttons with aria-current; Continue first on phones; 44 px targets | ux-reviewer PASS (round 5, the whole branch on the final build) | numbered timeline stepper; one flat card per group; eye and spark on the section headings |
| Writing assistant | `editor-consent`, `editor-assistant` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | consent dialog (API wording verbatim); demo fallback (no model); suggestion with Now, Suggested, Use this and Undo (unit); every refusal (unit) | modal focus trap, Escape is Not now, focus moves to the answer heading | ux-reviewer PASS (round 5, the whole branch on the final build) | the answer lives in the editor's panel; viewport shot for the dialog |
| Check a certificate (/verify) | `verify`, `verify-file` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | invalid id (field error), file chosen, no match (error callout with the fingerprint), match (unit), too large, network (unit) | GET form works without JS; file control 44 px; Check certificate the one primary | ux-reviewer PASS (round 5, the whole branch on the final build) | lookup in a lattice-edged sheet with the seal; file check as a flat card |
| Certificate record (/verify/{id}) | `verify-record`, `verify-notfound` | 5 | 4 | 4 | 4 | 5 | 5 | 0 | timestamped, pending (unit), not found, rate limited and unavailable (retry) | token and keys links as separate targets; Check file primary | ux-reviewer PASS (round 5, the whole branch on the final build) | the public record as a sheet: lattice edge, seal, warm check, fingerprint in groups; empty state with the drawing |
| Organisation Home | `org-home` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | needs us, nothing waiting, empty inbox (E2/E1/unverified sentences), held count, two-step on (one quiet line)/off/required, not a member, a failed read as "Could not be read just now" (unit) | tile links, card links, 44 px Open the Inbox | round 2 fixed (failed reads never read 0; due date on one line; sparkline from 5 items) | four tiles from the lists the page reads; real data: `org-home-*` |
| Inbox (Sent to you) | `org-inbox` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | rows with stage chip (link to the tracker), held callout, empty by verification level, stale cursor, refused (e2e) | tabs as links with aria-current; row is the link; chip 44 px | ux-reviewer PASS (round 5, the whole branch on the final build) | rows kept (summary and ask read as a list); P18 tokens |
| Inbox (Scout matches) | `org-matches` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | scout panel, matches with fit bar, no scout (owner and member), no matches, unavailable proposal | row is the link; Change the scout named by its niches | ux-reviewer PASS (round 5, the whole branch on the final build) | |
| Proposal (teaser and NDA step) | `org-proposal`, `org-nda` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | NDA step, accepted, viewing, every refusal (unit), step-up code, NDA outdated, draft wording note | Accept and view the one primary (full width on phones); NDA text a scrollable region | ux-reviewer PASS (round 5, the whole branch on the final build) | NDA text in a card; logging notice as a lock callout |
| Full proposal (marked page) | `org-proposal-full`, `org-proposal-full-frame` | 4 | 4 | 4 | 4 | 5 | 4 | n/a (API page, no script; axe runs on the host page: 0) | viewer mark, owner preview (unit, backend), attachments and links, light and dark | links open outside the sandbox; Close full proposal | round 2 fixed (dark inside the dark app through the embedder's colour scheme; dates as the product writes them) | P18 palette and serif title in a page that loads nothing; the per-viewer mark kept at ink 14 % / 0.8rem (reviewer MAJOR), a gradient lattice echo |
| Who has seen this | `idea-views` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | views, none yet (empty state with drawing), could not load (unit) | static cards (no link) | ux-reviewer PASS (round 5, the whole branch on the final build) | avatar cards; real data: Brian's proposal opened by Telco A |
| Scout match | `org-match` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | offered (signatory), not offered with the reason (reviewer, shown), step-up, sent, refusals (unit); unavailable, not found | aria-disabled button keeps focus and names its reason; Express interest the one primary when offered | ux-reviewer PASS (round 5, the whole branch on the final build) | "Why this matches" in a wash card under the fit meter |
| Scout form | `org-scout` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | new, edit (pause/resume), restored draft, plan limit, schedule not on plan (upgrade link), preview, refusals (unit) | 44 px checkboxes and radio cards; Save scout the one primary | ux-reviewer PASS (round 5, the whole branch on the final build) | three flat cards: what it looks for, schedule, the email digest |
| Discover | `discover`, `discover-projects`, `discover-gap`, `discover-niches` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | problems, projects, opportunity gap, cold start, filtered empty, no niches (unit, e2e); niches picker with the activity consent | native disclosures (no script); Filters disclosure; card titles the only links; Start a proposal per card | round 2 fixed (was hierarchy 3, delight 3: rows with 3–4 meta lines); round 3 fixed (the badge's short form from the locale, `discover.trendingShort`, split at the sentence's last colon) | compact cards two across as Home's recommendations: one meta line, chips, statement, a footer with the count, the provenance badge and the way to start |
| Problem card | `problem` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | developer-reported, AI-drafted with sources, seeded, not found | Start a proposal the one primary; the portal's navigation stays | round 2 fixed (was delight 3: half a page empty); round 3 fixed (the confidence band follows the percentage shown: 0.799 reads High (80%)) | a lattice-edged sheet like the certificate and /verify; the facts under a rule |
| Plan & billing | `billing`, `billing-org` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | developer and organisation ladders, current plan, upgrade target, not sold here, refusals and not a payer (unit) | one primary (the next plan up); Upgrade links 44 px; the portal's navigation stays | round 2 fixed (was hierarchy 3 at 1440: one column) | plans as cards two across from 1024 px with a check per entitlement; the current plan in the accent border |
| Checkout (simulated M-Pesa) | `checkout`, `checkout-waiting`, `checkout-success` | 4 | 4 | 4 | 4 | 5 | 5 | 0 | confirm, starting, waiting, stalled, succeeded (plan active or not), failed (reasons), cancelled, lost and refused (the handset idle), every start refusal (unit) | steps list with aria-current; the new step takes focus; one primary per step | round 2 fixed (was hierarchy 3 on phones: the handset above the action, keys that looked like buttons); round 3 fixed (after a failed or cancelled payment the step stood on reads Not paid, never Done) | the drawn handset follows the step on phones; its keys are dashed shapes; success in the warm tone |
| Staff: Research | `admin-research`, `admin-research-candidate` (skipped on this stack: every saved excerpt is already a card; the review page is covered by e2e/research.spec.ts and unit tests) | 4 | 4 | 4 | 4 | 5 | 4 | 0 | start a run (running, finished, failed), queue empty, runs as a dense table, saved excerpts folded, step-up, not an admin | Start run the one primary; row links keep a 44 px band | ux-reviewer PASS (round 5, the whole branch on the final build) | DataTable: calm dense rows, stacked cells with their column names on phones |
| Staff: Moderation | `admin-moderation`, `admin-moderation-case` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | open and decided views, empty views, case with flagged fields, decided case, step-up, not allowed (unit) | Review the oldest case the one primary; Approve/Reject on the case | ux-reviewer PASS (round 5, the whole branch on the final build) | the queue as a DataTable; at most two status marks per row |
| Staff: Claims | `admin-claims`, `admin-claim` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | review, in progress, closed views, empty views, SLA due/today/overdue marks, unnamed organisation, read-only claim | no primary (read only); row link 44 px band | ux-reviewer PASS (round 5, the whole branch on the final build) | the queue as a DataTable; the claimant's domain under their name |
| Settings: Security | `settings-security` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | two-step on/off/required, enrolment steps and codes (unit, e2e), recovery codes, password with and without one, errors | tabs as links under the one h1; Back to home above it; Show password 44 px | round 2 fixed (was hierarchy 3: tabs above the h1, Back inside the card); round 3 fixed (both cards' descriptions at one body size, the recovery lead at 60ch; ux-reviewer round 5 PASS) | h1 "Settings", the tabs, two flat cards with the one card-heading style |
| Settings: Notifications | `settings-notifications` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | choices, saved, wording changed (refused), none | checkboxes 44 px; Save choices the one primary | round 2 fixed (as Security) | h1 "Settings", the tabs, the subject as the card's heading |
| Help | `help`, `help-public` | 4 | 5 | 4 | 4 | 5 | 4 | 0 | signed in (account menu) and public (Log in link) | in-text link to Notifications | round 2 fixed (Show the tour again for the two portals; the portal's navigation stays); round 3 fixed (the button's answer takes focus, never <body>; ux-reviewer round 5 PASS) | editorial type only; no card needed |
| Terms | `terms` | 4 | 4 | 4 | 4 | 5 | 3 | 0 | placeholder text (legal pack pending, D-39) | | ux-reviewer PASS (round 5, the whole branch on the final build) | the legal placeholder in a sheet; delight waits on the real text |
| Companies and one organisation | `companies`, `company` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | grouped by niche, search, filters, stale cursor, next page, not found | Show companies the one primary; org names the row links | ux-reviewer PASS (round 5, the whole branch on the final build) | dense two-column directory kept |
| Engagements lists (developer, organisation) | `dev-engagements`, `org-engagements` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | grouped by idea (developer), Needs us / Everything else (organisation), empty, refused (unit) | rows are the links; Open the idea per group | ux-reviewer PASS (round 5, the whole branch on the final build) | rows kept; chips and the warm "Your turn" |
| Loading state (every route group) | removed in round 2 (reviewer BLOCKER): P16-B measured route-level `loading.tsx` at +0.35–0.7 s LCP and it turns the auth redirects into streamed 200s; pending states stay in place (LinkPending, aria-busy forms, the tracker's refresh) | – | – | – | – | – | – | n/a | – | – | – | no route-level skeleton: the page arrives whole |
| Closed engagement (celebration) | `tracker-closed` | 4 | 4 | 4 | 4 | 5 | 5 | 0 | first visit (seal draws, dots fall, buzz), dismissed and remembered per device (unit), reduced motion (dots rest) | one button; storage off follows the cookie, the server's own answer, so the card the server drew is never pulled away | round 3 fixed; ux-reviewer round 4 MAJOR fixed (the before-paint hide covers the shell, so the button is never painted alone: 0 painted frames, CLS 0 on the storage-only path, Lighthouse 99–100 light and dark), round 5 PASS (one capped cookie for the last eight engagements instead of one per engagement for a year; a card storage remembers but the cookie let go is hidden before paint and removed by hydration, never painted; a marker another page left never hides an unseen card: both pinned by between-tasks tests) | the seal in the warm tone; no empty actions card on a closed tracker |
| Confirm dialogs (bottom sheets) | `dialog-sheet` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | delete idea, withdraw pitch, assistant consent (every ConfirmDialog) | focus on Cancel; Escape closes; rises once, still under reduced motion | ux-reviewer PASS (round 5, the whole branch on the final build) | a bottom sheet with a grab mark under 640 px, centred above |
| Haptics | (lib/haptics.ts; unit) | n/a | n/a | n/a | n/a | n/a | 4 | n/a | success (payment confirmed, idea published, NDA accepted, interest sent, engagement closed), warn (payment failed or cancelled), tap (dialog confirm); silent without the Vibration API or under reduced motion | | ux-reviewer PASS (round 5, the whole branch on the final build) | words and colour carry the meaning; the buzz only confirms |
| Emails (EM1 registered, EM2 approval, EM3 scout digest, EM7 daily digest, N17 interest, auth: confirm, sign-in link, account exists, security notice) | `email-em1`, `email-em2`, `email-em3`, `email-em7`, `email-n17`, `email-auth-login`, `email-auth-security` (rendered samples at 640 px) | 4 | 4 | 4 | 4 | 5 | 4 | n/a | every kind through one frame (`_brand.html.j2`); the plain-text parts unchanged; the companion's daily check-in (REQ-REM-00) keeps its parity markup on purpose | one button per email; the link's address under it in the auth emails | ux-reviewer PASS (round 5, the whole branch on the final build) | paper, accent band over an ochre hairline, serif wordmark, white sheet, quiet footer; no images or gradients, so every client draws the same |
| Teaser checks (editor step 1, P19) | `editor-checks` (`docs/demo/screenshots/p19/`) | 4 | 4 | 4 | 4 | 4 | 4 | 0 | overlap none "compared with N", over-disclosure named by the rules (warn only), demo fallback chip, today's last overlap from the server, the daily limit in words (seen on the stack when the shots ran Amina out of checks; unit + e2e), not saved, every refusal (unit) | two secondary buttons, Enter and Space, each answer in its own polite live region, focus stays on the button, Continue the one primary, the card's chunk loads on the first press | pending (P19 round) | quiet card between the teaser and the assistant; the field list reads "how, not what: summary" (the card's wording, the field lower-cased through Intl.ListFormat) |
| Organisation: Problems (P19) | `org-problems`; `org-problems-empty` skipped (SACCO B holds the e2e's Briefs; the empty state is one sentence and Post a brief in `problems-pages.test.tsx`) | 4 | 4 | 4 | 4 | 5 | 4 | 0 (was heading-order on all four variants: fixed) | published, closed, in review, posted note, member who cannot post, stale cursor, refused (unit) | Post a brief the one primary (full width on phones); the card's title is its link | pending (P19 round) | fixed: the list is named by a hidden h2 so the h3 titles follow the h1 (an h2 title took the display serif and the underline: caught on the re-shot and reverted to h3) |
| Organisation: Post a brief (P19) | `org-brief-new`, `org-brief-new-refused` | 4 | 4 | 4 | 4 | 4 | 4 | 0 | blank, plan full (the notice above the form and the 402 naming Starter after a press), field checks (title first focused), 403 and 422 refusals, word meter at 120 (unit) | three flat cards as the scout form; radio cards 44 px; a refused band focuses its radio; Post the brief the one primary | pending (P19 round) | with the plan full the page says so three times (cap line, notice, then the 402): left as built, see below |
| Organisation: one Brief (P19) | `org-brief` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | published (See it as developers do), in review, not approved, closed, not found (unit) | Close this brief a secondary, confirmed step (no primary) | pending (P19 round) | the state note as a callout, the statement large over the facts |
| Discover: Briefs (P19) | `discover-briefs` | 4 | 4 | 4 | 4 | 5 | 4 | 0 | one Brief, none (unit), filtered | four tabs fit 360 px with "Gap" (measured: the P19-F card); card title the link; Start a proposal from this brief | pending (P19 round) | the card as Discover's problem cards; one badge "Posted by <organisation>"; budget and deadline on their own line |
| Problem page of a Brief (P19) | `problem-brief` | 5 | 4 | 4 | 4 | 5 | 4 | 0 | open Brief (its own start action), closed Brief (plain start and a quiet line, unit) | Start a proposal from this brief the one primary | pending (P19 round) | fixed: Region read "KE-30, Kenya"; it says "Nairobi City, Kenya" (every problem with a county) |
| Staff: Brief by in the queue (P19) | `admin-moderation-brief` (viewport at the row: the queue holds e2e cases) | 4 | 4 | 4 | 4 | 5 | 4 | 0 (first full run on this build; skipped in the last, the scene's Brief then published) | Brief by <organisation>, Problem Brief when the organisation is not listed (unit) | as the queue | pending (P19 round) | |
| Notifications page (P19) | `notifications`, `notifications-empty` (replace the mock-API shots) | 4 | 4 | 4 | 4 | 5 | 4 | 0 | unread and read rows in Nairobi day groups, empty (one sentence, one action), stale cursor, mark all read (done, failed), slow count (unit, e2e) | the row is the link and marks read (middle click too); Mark all as read the one secondary; no primary | pending (P19 round) | real rows from the tracker: a pitch's receipt, Under review, Approved to proceed (non-binding) |
| Bell (P19) | `bell` (top bar at 375) | 4 | 4 | 4 | 4 | 5 | 4 | 0 | none, a count, 99+ (unit) | 44 px link; the count in its name ("Notifications, 3 unread") | pending (P19 round) | badge in the accent over the bell, ringed in the paper colour |

## Round 2 (2026-10-01): the gate's measurements on the final build

Lighthouse 12 (mobile default: simulated Slow 4G, Moto G class; `--force-dark-mode` for dark), one run per cell unless
noted, signed in through the demo accounts. Performance ≥ 90 and accessibility 100 everywhere, light and dark; CLS 0.

| Page | Light perf / LCP | Dark perf / LCP |
|---|---|---|
| Landing `/` | 91–95 / 2.5–2.9 s (three runs) | 94–98 / 2.3–2.8 s |
| Log in | 99 / 2.0 s | 97 / 2.5 s |
| Verify record | 97 / 2.3 s | 98 / 2.0 s |
| Developer Home | 97–99 / 2.0–2.1 s (first visit, the tour showing); 2.05–2.88 s, median 2.64, for a returning visitor whose LCP is the Needs-you card (ux-reviewer, five runs) | 97–99 / 2.0–2.2 s; returning 2.04–2.64 s |
| Discover | 99 / 2.0 s | 98 / 2.4 s |
| Idea (certificate) | 98 / 2.1 s | 98 / 2.1 s |
| Developer tracker | 98 / 2.3 s | 98 / 2.3 s |
| Plan & billing | 99 / 2.2 s | 99 / 2.2 s |
| Organisation Home | 98 / 2.4 s | 98 / 2.5 s |
| Organisation Inbox | 98 / 2.4 s | 99 / 1.9 s |
| Organisation tracker | 97 / 2.6 s | 99 / 2.1 s |
| Staff Research | 99 / 2.2 s | 99 / 2.1 s |

What moved the numbers: the route-level loading states went (P16-B's decision; they had streamed a skeleton first),
the tour arrives with the page (a cookie the server reads; CLS 0.38 → 0 on both Homes), the display face is instanced
to its one weight (132 → 42 KB) and the text face to the weights in use (45 → 35 KB), and the two above-the-fold
faces are preloaded at high priority ahead of the async scripts (next/font had emitted no preload: with the scripts
blocked the landing's LCP was 1.96 s, with them 2.88 s). The landing's LCP, its 56 px headline in the display face,
still sits at 2.5–2.9 s in this container (run-to-run spread ±0.2 s), and the developer Home for a returning visitor
(no tour; the first Needs-you card's title is the largest text) reads 2.0–2.9 s with a median of 2.64 s across the
ux-reviewer's runs: the last 0.3 s is the swap into the self-hosted faces on a first, uncached, Slow 4G visit; later
visits have both faces cached for a year. Both are recorded in DECISIONS-NEEDED (D-53) with the options. Every other
signed-in page measured at or under 2.5 s.

JS budget (`scripts/js-budget.mjs`, gzipped script bytes until idle, 150,000 limit): `/settings/security` 147,301
(the largest route; the tracker 149,8xx in round 1 before the Actions frame change), every other measured route under
it; headroom is thin on the tracker and the sign-up page, so the next import on either must be weighed first.

Full Playwright suite on the compose stack (`npx playwright test`, 164 scenarios × mobile-360 and desktop): green on
the final build (round 3: 162 passed and the two Discover scenarios, which read the badge's deliberate short form, green on re-run; `pr.yml` green on the final head, see PROGRESS.md); the design-shots runner: 60 screens × 4 variants, strict axe 0
violations on every one (`docs/demo/axe-p18.json`), at most one `[data-primary]`, no sideways scroll.

## Round 3 (2026-10-01): reviewer rounds 6–11 on the final build

The adversarial reviewer ran six more rounds over the round-2 commits and their fixes (one MAJOR each in rounds 6–9,
a BLOCKER on a flaky test in round 10, PASS in round 11 for the whole range). What changed: the tour's reset unmarks
the document; the celebration keeps one small cookie and a before-paint hide whose timing through Next's transition
hydration is pinned by tests that sample the DOM between tasks; confidence bands on the percentage shown; the trend
badge's short form comes from the locale; a failed payment never stands on a step called Done; the security card's
descriptions share one size. Each fix is its own commit.

JS budget on the rebuilt stack (`scripts/js-budget.mjs`): the developer tracker 149,313 bytes (open and closed: the
celebration's client half is the shell only), `/settings/security` 147,325, the developer Home 144,088; all under
150,000.

Lighthouse, returning visitor (the tour and the celebration remembered), three runs each where it matters: developer
Home light 97–99 / LCP 2.04–2.63 s, dark 2.02–2.64 s; organisation Home 100 / 1.88–1.91 s; landing 95–96 / 2.80 s;
CLS 0 and accessibility 100 on every run. The landing and the first visits are as recorded in D-53, decided (a) now and
(d) before the pitch: the laptop and host readings go in a table under this one when they are taken.

The ux-reviewer's rounds 4 and 5 on the rebuilt stack: round 4 found the celebration's "Got it" button outside the
before-paint hide (a lone button painted, then removed: CLS 0.037 at 375), a focus drop after "Show the tour again"
by keyboard, the recovery lead with no line-length cap, and the Home's and the tracker's first-visit LCP missing from
D-53; all four fixed in their own commits, and round 5 verified each on the running build (0 painted frames and
CLS 0 on the storage-only path, light and dark; focus on the status line; the lead at 60ch; D-53 updated) and
passed the whole branch. Final JS budget: the tracker 149,321 bytes, `/settings/security` 147,332, `/help` 142,500.

## P19 measurements (2026-10-02)

Shots: `frontend/demo/design-shots.spec.ts` (the P19 entries; `SHOT_FILTER` as in its config), 1440 and 375 px, light
and dark, against the compose stack's API and data with the web app built from this branch (the fixes above; the
editor, Discover and notification code as on the stack). Strict axe: 38 shots, 0 violations, at most one
`[data-primary]`, no sideways scroll (`docs/demo/axe-p19.json`; the moderation row's four shots were 0 on the first full
run of the same build). The runner makes its own Brief (Telco A's reviewer, approved in the queue), a draft of
Brian's and two test accounts for the bell, and closes or deletes them at the end.

JS budget (`scripts/js-budget.mjs`, gzipped script bodies until idle, 360 px, limit 150,000; production build of
`7d254d2` on the compose stack, signed in as the demo accounts; the gate's final build):

| Route | Bytes | |
|---|---|---|
| `/dev/engagements/<id>` and `?tab=history` (the tracker with the side states, both sides' chunks the same) | 149,979 | ok (21 B left) |
| `/org/engagements/<id>` | 149,979 | ok (21 B left) |
| `/dev/ideas/<draft>/edit` (page load) | 149,819 | ok (181 B left; 149,774 on `aaae794`, the magnifier icon since) |
| … after pressing "Check overlap" | 154,340 | on demand, reported apart (D-28 addendum); the assistant's press read 155,801 on `aaae794` |
| `/dev/ideas/<published, with a chosen problem>/edit` | 152,306 | over since P18: see below |
| `/dev/discover?view=briefs` | 142,335 | ok |
| `/problems/<brief>` | 141,925 | ok |
| `/dev` (the bell) | 144,088 | ok |
| `/notifications` | 143,187 | ok |
| `/org` | 143,684 | ok |
| `/org/problems` | 142,462 | ok |
| `/org/problems/new` | 147,135 | ok |
| `/org/engagements`, `/org/inbox`, `/dev/engagements` | 141,925 | ok |

The tracker went from 149,321 B (P18) to 149,979 B with the side states' banner, stepper chips, rows, the lazily loaded
sheets and the busy announcement: the four sheets and their forms load on the first press; everything else on that
route now needs an offset or `next/dynamic`.

The editor's page load grew from 146,247 B (P13-F) to 149,774 B: the next import on that route must be weighed first.

Found while re-measuring after the ux round (build `bf64671`, 152,260 B; 152,306 B on the final build `7d254d2`): the
editor of an idea that already has a chosen problem (the usual case once an idea is published) also loads the problem
picker's panels chunk at page load (2,470 B, the linked list and its search), and reads **over the budget by about
2,300 B**. The chunk and its loading rule are
P16's (`editor/ProblemPicker.tsx`), and the shared chunks grew in P18, so this variant has been over since P18
(about 151.9 KB then); P19's checks card added 328 B to the editor's own chunk (6,068 → 6,396 B) and the draft editor
(the measured route) stays under. Deferring the panels alone is not enough (it leaves about 150.3 KB). The fix is a
task of its own for the next phase: split the picker so an idea with chosen problems renders its linked list
statically and loads the search and the new-problem fields on "Link another problem" (about 2 KB), and move the
editor's attachments step behind its own import (the rest). Recorded in PROGRESS.md's P19 report as an open item.

Lighthouse 12 (mobile default, simulated Slow 4G; `--force-dark-mode` for dark), one run per cell on the compose stack
(`aaae794`) unless noted:

| Page | Light perf / a11y / LCP | Dark perf / a11y / LCP |
|---|---|---|
| `/org/problems` | 99 / 98 / 1.9 s (heading-order; 100 / 100 / 1.9 s on the fixed build) | 99 / 98 / 1.9 s (99 / 100 / 1.9 s fixed) |
| `/dev/discover?view=briefs` | 99 / 100 / 1.8 s | 93 / 100 / 2.8 s once, then 99 / 100 / 2.0 and 2.1 s |
| `/notifications` | 99 / 100 / 2.1 s | 99 / 100 / 1.9 s |
| `/dev/engagements/<id>` with a side state (final build `7d254d2`) | 99 / 100 / 2.2 s | 99 / 100 / 2.2 s |
| `/org/engagements/<id>` with a side state (final build) | 99 / 100 / 2.2 s | 97 / 100 / 2.5 s (2.53) |
| `/notifications` (final build) | 99 / 100 / 1.9 s | 98 / 100 / 2.5 s (2.50) |
| `/org/problems` (final build) | 97 / 100 / 2.5 s (2.54) | 100 / 100 / 1.9 s |

CLS 0 everywhere.

Left as built, for the ux-reviewer: with the plan's open Briefs in use, "Post a brief" still shows the whole form under
the plan line and the full-plan notice, and a press adds the 402 below it (the same fact three times); the form is
not disabled because closing a Brief in another tab frees the slot. A single notice (the plan line folded into it)
would read better.

## P20 measurements (2026-10-04): the Jacaranda redesign (D-55)

Shots: `frontend/demo/design-shots.spec.ts` with `SHOTS_DIR=docs/demo/screenshots/p20` (every product screen of the
P18 and P19 sets in the new design), 1440 and 375 px, light and dark, against the compose stack rebuilt from this
branch. Strict axe: every shot 0 violations, at most one `[data-primary]`, no sideways scroll. The first full run found
one: the landing's hero badges, read by axe while the cards were still fading in (partial opacity); the cards now slide
into place without a fade, and the re-run reads 0. The walkthrough's screenshots (`docs/demo/screenshots/*.jpg`) were
re-recorded on a fresh `demo.py reset --yes` (the demo story 1/1).

JS budget (`scripts/js-budget.mjs`, gzipped script bodies until idle, 360 px, limit 150,000; production build of this
branch, signed in as the demo accounts). All 43 routes measured are under; the tightest:

| Route | Bytes | |
|---|---|---|
| `/org/inbox/scouts/new` and `/<id>` | 149,892 | ok (untouched by P20) |
| `/dev/ideas/new` and `/dev/ideas/<published, with a chosen problem>/edit` | 149,713 | ok: was 149,719 and 152,206 (over since P18) |
| `/dev/engagements/<id>`, `/org/engagements/<id>` | 149,534 | ok: was 149,979 (P20-4 moved the forms' helpers out of the first load) |
| `/signup` | 149,214 | ok |
| `/auth/link` | 148,253 | ok |
| `/dev/ideas/<id>` | 148,176 | ok |
| `/` (the new landing) | 139,503 | ok |

The editor fix is the one P19 recorded: an idea with chosen problems shows them as a plain list, and the search and
the new-problem fields load on "Link another problem"; the publish checklist and the link checks moved to
`app/(app)/dev/ideas/checklist.ts`, which the review step loads and hands to the editor.

Lighthouse 12.8.2 (mobile default, simulated Slow 4G; dark through `--blink-settings=preferredColorScheme=0`),
production build of this branch, one run per cell after the landing fix:

| Page | Light perf / a11y / LCP | Dark perf / a11y / LCP |
|---|---|---|
| `/` | 97 / 100 / 2.6 s (96–99, 2.2–2.7 s over four runs) | 98 / 100 / 2.2 s (96–99, 2.2–2.7 s) |
| `/login` | 99 / 100 / 1.9 s | |
| `/verify/<id>` | | 99 / 100 / 2.0 s |
| `/dev` | 99 / 100 / 2.1 s | 99 / 100 / 2.0 s |
| `/dev/discover` | 98 / 100 / 2.1 s | |
| `/dev/engagements/<id>` | 97 / 100 / 2.6 s | |
| `/org/engagements/<id>` | | 99 / 100 / 2.0 s |
| `/org/inbox` | 99 / 100 / 2.0 s | |

Best practices 100 and CLS 0 everywhere. The landing's first build read 87 / 91 (TBT 340 ms, style and layout
520 ms): a page-wide `html:has(#hero-title)` rule and a blurred glow layer; both are gone. The landing's LCP element is
the hero's lead paragraph; its first, uncached Slow 4G visit stays around D-53's 2.5 s line (2.2–2.7 s), as decided
there.

## P21 measurements (2026-10-05): messages, the shortlist, saved searches (D-57)

Shots: `frontend/demo/design-shots.spec.ts` with `SHOTS_DIR=docs/demo/screenshots/p21` and the P21 filter, 1440 and
375 px, light and dark, against the demo stack on :3000 (reset at `0b81dd3`, not rebuilt). 14 screens, 56 shots:
Messages for Amina and for SACCO B's owner (the seed's thread), a thread not open yet from both sides (Brian's pitch
to Telco A, at SUBMITTED), History with the message entries, the Inbox with its stars, the proposal page's star, the
Shortlist and Compare as Telco A's reviewer, Discover with Amina's saved search (the list open) and the save form,
notification settings for a developer and an organisation (the two new rows), and a reported message in the moderation
console. Strict axe: every shot 0 violations, at most one `[data-primary]`, no sideways scroll. Compare needs two
shortlisted proposals: the run starred one more Telco A Inbox proposal (Cashless market-fee collection) and it was
taken off afterwards, so the seed's one entry is back. The moderation shot uses a message case an e2e run had already
reported; the shots post and report nothing. Discover's lists also show problems that e2e runs left on this stack.

JS budget (`scripts/js-budget.mjs`, gzipped script bodies until idle, 360 px, limit 150,000; the demo stack's
production build, signed in as the demo accounts). All 58 routes measured are under (`/admin` redirects to
`/admin/research` for the staff admin and was skipped); the tightest, then every P21 route:

| Route | Bytes | |
|---|---|---|
| `/org/inbox/scouts/new` and `/<id>` | 149,920 | ok (P20: 149,892) |
| `/dev/engagements/<id>/messages`, `/org/engagements/<id>/messages` | 149,627 | ok: 373 B left |
| `/dev/engagements/<id>` (also `?tab=history`), `/org/engagements/<id>` | 149,570 | ok (P20: 149,534) |
| `/admin/moderation/cases/<message case>` | 149,517 | ok |
| `/signup` | 149,236 | ok |
| `/dev/ideas/new`, `/dev/ideas/<id>/edit` | 149,014 | ok (P20: 149,713) |
| `/dev/discover` (every view) | 147,721 | ok |
| `/settings/notifications` (developer and organisation) | 144,899 | ok |
| `/org/inbox/shortlist` | 143,468 | ok |
| `/org/inbox` (and `?tab=matches`) | 143,237 | ok |
| `/org/inbox/shortlist/compare?ids=<a>,<b>` | 141,823 | ok |

The Messages routes and the tracker are within 500 B of the line: the next import there must be weighed first.

Lighthouse 12.8.2 (mobile default, simulated Slow 4G; dark through `--blink-settings=preferredColorScheme=0`), the
demo stack's build, signed in through the session cookie; the Messages routes three runs per cell (range), the others
one:

| Page | Light perf / a11y / LCP | Dark perf / a11y / LCP |
|---|---|---|
| `/dev/engagements/<id>/messages` (Amina) | 95–97 / 100 / 2.1–2.7 s | 92–95 / 100 / 2.7–2.8 s |
| `/org/engagements/<id>/messages` (SACCO B) | 95–98 / 100 / 1.9–2.7 s | 93–97 / 100 / 2.0–2.8 s |
| `/org/inbox/shortlist` | 100 / 100 / 1.9 s | 96 / 100 / 2.6 s |
| `/org/inbox/shortlist/compare?ids=…` | 99 / 100 / 1.9 s | 100 / 100 / 1.5 s |
| `/dev/discover` | 97 / 100 / 2.3 s | 97 / 100 / 2.5 s |

Every cell meets performance ≥ 90 and accessibility ≥ 90; best practices 100 and CLS 0 everywhere. The Messages
routes' LCP element is the page title (the tracker's `h1`, as on the tracker in P20, 2.6 s); several runs land at
2.6–2.8 s, above AC-UX-3's 2.5 s, as the tracker's first uncached Slow 4G visit did (D-53).
