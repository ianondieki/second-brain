# UI inventory for the polish pass (P16, REQ-UX-01..04)

Read-only inventory of `frontend/app`, `frontend/components` and the emails a demo run puts in Mailpit. It describes the
code as it is on branch `claude/gracious-wright-ywfvei`. Nothing here is a plan. Paths are relative to `frontend/`
unless they start with `backend/` or `docs/`. Line numbers are from this checkout.

## 0. Cross-cutting facts

| Topic | What the code does today |
|---|---|
| Route count | 42 `page.tsx` files: public 10, developer 12, organisation 8, either signed-in side 5, staff admin 7. |
| Loading | No `loading.tsx` anywhere. No route-level `<Suspense>`. Every page is server-rendered and blocks until its API calls answer (most loaders use a 5 s `AbortSignal.timeout`). Loading exists only as client busy states (button `busy`, "Saving…", "Checking…") and 11 inner `<Suspense>` boundaries (section 3.4). Every route below is "missing" for page-level loading unless its row says otherwise. |
| Error | Three route-group boundaries, all `LazyErrorScreen` then `components/ErrorScreen.tsx` (title, one sentence, one "Try again" button, no link home): `app/(public)/error.tsx`, `app/(app)/error.tsx` (covers `/dev`, `/org`, `/billing`, `/settings`, `/problems`), `app/(admin)/error.tsx`. No `global-error.tsx`. |
| Not found | No `not-found.tsx`. Next's default 404 is used. `/admin/**` is rewritten to an unmatched path for anyone who is not staff (`proxy.ts:48`), and `staffContext` calls `notFound()` (`app/(admin)/admin/staff.ts`). Unknown ids elsewhere render an inline empty state instead. |
| Signed out on a signed-in route | `requireMe()` redirects to `/login` (`lib/api/server.ts:63`); a session still owing the second factor goes to `/auth/mfa` (`:64`). Wrong side (developer on `/org`, org member on `/dev`) is redirected to their own home (`homeFor`). |
| Strings | Every user-visible string found comes from `locales/en.json` (56 top-level namespaces) via `getTranslations`, `useTranslations`, or `ClientStrings`/`useStrings`. A grep for JSX text nodes, `aria-label`/`placeholder`/`title`/`alt`/`label` literals, and `{"..."}` literals in non-test `.tsx` under `app/` and `components/` found none: no hard-coded English in JSX. `locales/sw.json` has the same line count (2231) as `en.json`. |
| Copy oddities worth a look | `locales/en.json` `legal.termsBody` is `[[LEGAL-PLACEHOLDER:tos]]` (shown on `/legal/terms`). `help.support.body` is "Support contact to be set." (`data-support-placeholder`, `app/(public)/help/page.tsx:49`). `companies.empty` is "None". The EM7 subject hard-codes "Bridge" (`backend/src/bridge/reminders/nudge.py:285`). |
| Native confirm | `window.confirm` and `alert(` are not used. Confirmations are native `<dialog>` (3). The editor uses `beforeunload` (`app/(app)/dev/ideas/editor/Editor.tsx:272`). |

Abbreviations used in the route tables: **L** = loading, **E** = empty, **Err** = error, **S** = success. "Shared EmptyState" is
`app/(app)/org/EmptyState.tsx` (one sentence, one link; `primary` makes the link the primary button). It is imported
by developer, billing, settings and admin pages too, although it lives under `org/`.

## 1. Routes

Who-can-see key: **out** = signed out; **dev** = developer; **org** = any organisation member; **staff admin** / **moderator** = `staff_role`.
Org seat roles gate only the actions named; the API decides them (the pages read them only where noted).

### 1.1 Public (`app/(public)`, 10 routes)

| Path | Portal | File | Who | Primary action | L | E | Err | S | Strings |
|---|---|---|---|---|---|---|---|---|---|
| `/` | public | `app/(public)/page.tsx` | out (no redirect for signed-in in page code) | `ButtonLink` primary "Create an account" (`:15`) | n/a (static) | n/a | `(public)/error.tsx` | n/a | en.json `landing` |
| `/login` | public | `app/(public)/login/page.tsx`, `LoginForm.tsx` | out | `SubmitButton` primary (`LoginForm.tsx:114`) | busy text via `login.submitting` / `magicLinkSending` (`:115`, `:118`) | n/a | inline `Alert` (`LoginForm.tsx:88`) | `continueAfterSignIn` redirect; magic link goes to `/signup/check-email?for=login` (`:79`) | `login`, `fields`, `validation`, `errors` |
| `/signup` | public | `signup/page.tsx`, `SignupForm.tsx` | out | `SubmitButton` primary (`SignupForm.tsx:288`) | busy text (`:289`); consents reload shows `signup.consentsRetrying` "Loading…" | consents fetch failed: `Alert` + secondary retry (`:260-261`) | `Alert` (`:156`) | `router.push("/signup/check-email")` (`:139`) | `signup`, `orgKind`, `fields`, `validation`, `errors` |
| `/signup/check-email` | public | `signup/check-email/page.tsx`, `CheckEmail.tsx` | out | none (Resend is a secondary `Button`, `CheckEmail.tsx:56`) | `busy` on resend | n/a | `Alert` (`:54`) | `Alert tone="ok"` resent (`:53`) | `checkEmail`, `errors` |
| `/auth/link` | public | `auth/link/page.tsx`, `LinkSignIn.tsx` | out (token in URL hash) | several by state: `ButtonLink` primary (`:146`), `Button` primary retry (`:165`), `SubmitButton` primary (`:210`) | `role=status` "Checking your link…" (`:177`) | n/a | `Alert` for send error (`:193`); interrupted and failed states are whole-screen copy | redirect via `continueAfterSignIn` (`:95`) | `link`, `fields`, `validation`, `errors` |
| `/auth/mfa` | public | `auth/mfa/page.tsx`, `MfaForm.tsx` | session waiting for the second factor only (`requirePendingMfa`); signed out goes to `/login`, fully signed in goes home | `SubmitButton` primary (`MfaForm.tsx:104`) | busy text (`:105`) | n/a | `Alert` (`:72`) | `continueAfterSignIn` (`:53`); sign out link in top bar | `mfa`, `validation`, `errors` |
| `/legal/terms` | public | `legal/terms/page.tsx` | out, any | none | n/a | n/a | `(public)/error.tsx` | n/a | `legal` (body is a `[[LEGAL-PLACEHOLDER:tos]]`) |
| `/help` | public; also renders `SignedInShell` when signed in | `help/page.tsx` | out, dev, org, staff (any) | none | missing | n/a | swallows a failed `getMe` and shows the public view (`:20-27`); else `(public)/error.tsx` | n/a | `help` (`help/sections.ts`) |
| `/verify` | public | `verify/page.tsx`, `FileCheck.tsx`, `VerifyShell.tsx` | out, any | plain `<button data-primary>` "Check" (`:53`) | `FileCheck` busy text (`FileCheck.tsx:90`) | n/a | field `error` on the id (`:43`); `FileCheck` `Alert` (`:71`) and result block (`:94-113`) | GET form redirects to `/verify/{id}` when the id is well formed (`:29`) | `verify`, `verifyFile` |
| `/verify/[certId]` | public | `verify/[certId]/page.tsx`, `VerifyRecord.tsx` | out, any | `FileCheck` primary when the record is found (`:81`); none otherwise | missing | "not found", "rate limited" or "unavailable" sentence plus one link (`:45-71`) | same three sentences; `(public)/error.tsx` for throws | record with status icon (`VerifyRecord.tsx:26`); non-canonical ids redirect (`:42`) | `verify`, `verifyFile` |

### 1.2 Developer portal (`/dev`, 12 routes; all require a developer session, other sides are redirected)

| Path | File | Primary action | L | E | Err | S | Strings |
|---|---|---|---|---|---|---|---|
| `/dev` | `app/(app)/dev/page.tsx` | `ButtonLink` primary "New proposal" (`:62`) | missing | no engagements: hand-rolled `data-empty-state` "Your engagements show here once you pitch one of your ideas to a company." with link "Go to My ideas" (`:70`); Recommended block has its own empty states (`RecommendedForYou.tsx:67`) | `(app)/error.tsx` | n/a | `home`, `devHome`, `recommendations` |
| `/dev/discover` | `dev/discover/page.tsx` | none (filters button is secondary, `DiscoverControls.tsx:108`) | missing | shared EmptyState (`DiscoverList.tsx:42,69,95`): "Nothing is trending or new yet." / "No project is trending or new yet." / "No rising problem is short of proposals right now." / filtered "Nothing here for this niche and county yet." | `(app)/error.tsx` | n/a | `discover` |
| `/dev/discover/niches` | `dev/discover/niches/page.tsx` | `Button` primary Save (`NichePicker.tsx:131`) | busy on save ("Saving…") | not a developer profile: shared EmptyState "Only developer accounts choose niches." (`:74`) | `Alert` (`NichePicker.tsx:124`); profiling toggle `Alert` (`ProfilingToggle.tsx:65`) | `Alert tone="ok"` "Saved. Your recommendations now use these niches." (`NichePicker.tsx:128`); `role=status` in `ProfilingToggle.tsx:58` | `likedNiches` |
| `/dev/companies` | `dev/companies/page.tsx` | `<button data-primary>` Search (`DirectoryFilters.tsx:52`) | missing | local `Empty`-style block (`DirectoryResults.tsx:92`): "No organisations match these filters." / "No organisations are listed yet."; stale cursor variant | `(app)/error.tsx` | n/a | `companies`, `orgKind` |
| `/dev/companies/[orgId]` | `dev/companies/[orgId]/page.tsx` | none | missing | unknown/unlisted id: `Empty` (`:70`) "This organisation is not in the directory." with back link | `(app)/error.tsx` | n/a | `companies`, `orgKind` |
| `/dev/engagements` | `dev/engagements/page.tsx` | none (by design, `:21`) | missing | hand-rolled `data-empty-state` (`:39`): "Pitch one of your ideas to a company to start an engagement." + "Go to My ideas" | `(app)/error.tsx` | n/a | `tracker` |
| `/dev/engagements/[id]` | `dev/engagements/[id]/page.tsx` -> `components/tracker/EngagementScreen.tsx` | per state: `Button` primary in `components/tracker/Actions.tsx:184` (`item.primary`) or `SubmitButton` primary in `CommandForm.tsx:113`; at most one is primary | action panel `<Suspense>` fallback "Working…" (`Actions.tsx:222`); busy buttons | refused/unknown: `components/tracker/Refused.tsx:14` (`data-empty-state`); no documents: `EngagementScreen.tsx:197` | `Alert` with tone per outcome (`Actions.tsx:150`); `ContactReveal.tsx:52`; `ShareTier2.tsx:93` | `Actions.tsx:150` notice then `router.refresh()` (`:126`); `ShareTier2.tsx:88` `Alert tone="ok"` | `tracker`, `trackerActions`, `tier2Share` |
| `/dev/ideas` | `dev/ideas/page.tsx` | `ButtonLink` primary "New idea" (`:42` with items, `:66` in the empty state; never both) | missing | hand-rolled `data-empty-state` (`:64`): "Write up your first idea: a short public teaser, then the confidential details." | `(app)/error.tsx` | `Alert tone="ok"` for `?removed=hidden|deleted` (`:49`) | `ideas` |
| `/dev/ideas/new` | `dev/ideas/new/page.tsx` -> `editor/EditorScreen.tsx` | `Button` primary "Continue" on steps 1-2 (`Editor.tsx:619`); "Publish" on step 3 (`Review.tsx:233`) | autosave status "Saving…" / "Saved" / "Not saved yet" (`Editor.tsx:629-647`, `role=status`); `<Suspense>` with status text (`Editor.tsx:534-553`) and `fallback={null}` (`:576`, `:589`, `ProblemPicker.tsx:47`); `Review` busy (`:233`) | no listed problems: `ProblemPanels.tsx:178` | `Alert` (`Editor.tsx:378`, `:557`; `Review.tsx:210,213`; `Attachments.tsx:143`; `AssistantPanel.tsx:260`) | publish redirects to `/dev/ideas/{id}?published=1` (`Review.tsx:127`); `AssistantPanel.tsx:262` `Alert tone="ok"` | `ideaEditor`, `ideaFields`, `ideaAssistant` |
| `/dev/ideas/[id]/edit` | `dev/ideas/[id]/edit/page.tsx` -> `EditorScreen.tsx` | as above | as above | idea missing: hand-rolled `data-empty-state` (`EditorScreen.tsx:43`) "This idea is not one of yours, or it was deleted." | as above; hidden/archived ideas redirect to the idea page (`:52`) | as above | as above |
| `/dev/ideas/[id]` | `dev/ideas/[id]/page.tsx` | `ButtonLink` primary "Pitch to companies" (`:117`) else "Edit idea"/"Continue editing" (`:121`); none when hidden | delete and withdraw dialogs show busy text (`DeleteIdea.tsx:89`, `WithdrawTag.tsx:96`) | not found (`:67`); no pitches (`Pitches.tsx:76`); nobody opened details (`WhoHasSeen.tsx:27`); "No full details yet." (`:228`); no certificate (`:320`) | status notices as `Alert` (`:108`, tone error for rejected); dialog `Alert`s (`DeleteIdea.tsx:78`, `WithdrawTag.tsx:89`) | `Alert tone="ok"` published (`:104`); delete redirects with `?removed=` (`DeleteIdea.tsx:50`); withdraw does `router.refresh()` | `ideas`, `ideaFields`, `ideaPitches`, `ideaViews`, `ideaDelete`, `tagWithdraw` |
| `/dev/ideas/[id]/pitch` | `dev/ideas/[id]/pitch/page.tsx`, `PitchForm.tsx` | `Button` primary "Pitch" in the sticky action bar (`PitchForm.tsx:287`, `data-action-bar` `:275`) | busy text (`:294`), fieldsets disabled while busy (`:200`, `:255`) | local `Empty` (`page.tsx:159`): not found, blocked by status, stale cursor, cap used, no matches, no companies | `Alert` (`PitchForm.tsx:407`) | result lists "sent" and "saved until they verify" (`PitchForm.tsx:431-470`) | `pitch`, `companies`, `orgKind` |

### 1.3 Organisation portal (`/org`, 8 routes; all require an organisation-side session)

All eight start with `orgContext` (`app/(app)/org/data.ts:40`): no membership or `?org=` not a member gives a shared EmptyState
("Your account is not a member of an organisation yet." / "...of this organisation."). Seat roles on the membership are
`roles[]` (`owner`, `admin`, `reviewer`, `signatory`, `finance` appear in code); pages gate on them only where noted.

| Path | File | Who (seat roles) | Primary action | L | E | Err | S | Strings |
|---|---|---|---|---|---|---|---|---|
| `/org` | `app/(app)/org/page.tsx` | any member | `<Link data-primary>` "Open Inbox" (`:82`); "Turn on two-step sign-in" via shared EmptyState `primary` when needed | missing | not-member state (`:36`); inbox summary sentence per verification (`inbox.emptyE2/E1/Unverified`) | inbox read failure is swallowed so home never shows the error page (`:51-55`) | n/a | `home`, `orgHome`, `inbox` |
| `/org/inbox` | `org/inbox/page.tsx` | any member; E1 orgs see only a held count | none on the list; "Turn on two-step sign-in" / "Enter code" via EmptyState `primary` on refusals (`:91-103`) | missing | shared EmptyState (`:87-105`, `:153`, `:159`): e.g. "No proposals yet: when a developer sends one to {org}, it arrives here."; tab "Scout matches": `ScoutMatches.tsx:61,68,98,104` ("No matches yet: ...") | refusals rendered as EmptyState | n/a | `inbox`, `scoutMatches` |
| `/org/inbox/[proposalId]` | `org/inbox/[proposalId]/page.tsx`, `FullProposal.tsx`, `NdaAccept.tsx`, `StepUp.tsx` | any member reads the teaser; the full proposal needs reviewer, signatory or admin, and a signatory must have accepted the Master Enterprise Terms (API refusals, en.json `orgProposal` ~`:411-414`) | `SubmitButton` primary "Accept and view" (`NdaAccept.tsx:104`) or `<Link data-primary>` (`FullProposal.tsx:128`, `:215`) | `StepUp` "Checking…" (`orgProposal.stepUpChecking`); `NdaAccept` busy (`:104`) | not found: shared EmptyState (`:51`); 70dvh sandbox frame (`FullProposal.tsx:56`) | `Alert tone="error"` (`NdaAccept.tsx:80`) | `router.replace(viewHref)` stays busy until the marked page replaces the step (`NdaAccept.tsx:63`) | `orgProposal`, `inbox` |
| `/org/inbox/matches/[matchId]` | `org/inbox/matches/[matchId]/page.tsx`, `ExpressInterest.tsx` | any member reads; Express interest only for a signatory of an E2 org (`role_required` en.json `:485`); reason shown as a fixed sentence plus a disabled-looking secondary button (`:150-161`) | `Button` primary "Express interest" (`ExpressInterest.tsx:175`), then `SubmitButton` primary (`:247`) | `SubmitButton` busy (`:247`) | not found / unavailable / refusal: shared EmptyState (`:54-63`) | `Alert` (`ExpressInterest.tsx:146`, `:184`) | `Alert tone="ok"` (`:153`); `router.push` to the new tracker (`:121`) | `scoutMatch`, `scoutMatches`, `expressInterest` |
| `/org/inbox/scouts/new` | `org/inbox/scouts/new/page.tsx` -> `ScoutScreen.tsx` | owner or admin only (`configuresScouts`, `org/scout.ts:52`); others get EmptyState "Only an owner or admin of {org} can set up the Scout Agent." (`ScoutScreen.tsx:77`) | `SubmitButton` primary (`ScoutForm.tsx:350`) | busy (`ScoutForm.tsx:350`); `ScoutPreview` | not found / refusal (`ScoutScreen.tsx:91-101`) | `Alert tone="error"` (`ScoutForm.tsx:335`); info `Alert`s (`:200-210`, `ScoutPreview.tsx:23`) | `router.push(doneHref)` (`ScoutForm.tsx:170`); "Saving…" | `scoutPage`, `scoutForm` |
| `/org/inbox/scouts/[scoutId]` | `org/inbox/scouts/[scoutId]/page.tsx` -> `ScoutScreen.tsx` | as above, plus pause/resume | as above | as above | unknown scout: EmptyState (`ScoutScreen.tsx:99`) | as above | as above | as above |
| `/org/engagements` | `org/engagements/page.tsx` | any member; an `OrgPicker` shows for several memberships | none on the list; EmptyState `primary` "Turn on two-step sign-in" when refused (`:56`) | missing | shared EmptyState (`:61`): "No engagements yet: they start when a developer pitches an idea to your organisation." + "Open the Inbox" | refusal EmptyStates (`:55-59`) | n/a | `tracker`, `inbox` |
| `/org/engagements/[id]` | `org/engagements/[id]/page.tsx` -> `EngagementScreen.tsx` | any member; actions depend on seat (signatory for approvals and signatures, per `components/tracker/Deal.tsx`); API decides | as `/dev/engagements/[id]` | as `/dev/engagements/[id]` | `Refused.tsx:14`, `EngagementScreen.tsx:197` | as tracker | as tracker | `tracker`, `trackerActions` |

### 1.4 Either signed-in side (`app/(app)`, 5 routes)

| Path | File | Who | Primary action | L | E | Err | S | Strings |
|---|---|---|---|---|---|---|---|---|
| `/billing` | `app/(app)/billing/page.tsx` | dev; org members who pay (`owner`, `admin`, `finance`; `billing/plans.ts:15`) via `?org=` | `<Link data-primary>` "Upgrade to {plan}" on the next plan up (`:186`); EmptyState `primary` for the 2FA refusal (`:68`) | missing | shared EmptyState for not-member, no-org, not-payer, 2FA refusals (`:46-78`) | as EmptyState | n/a | `billing` |
| `/billing/upgrade` | `billing/upgrade/page.tsx`, `Checkout.tsx` | as `/billing` | `Button` primary start (`Checkout.tsx:307`), check again (`:166`), restart (`:376`); `<Link data-primary>` on success (`:360`) | `role=status` with `motion-safe:animate-pulse` clock "Checking the payment…" (`Checkout.tsx:156-157`); "Starting…" | shared EmptyState for unknown plan, already on plan, free plan, not sold (`page.tsx:79-107`) | `Alert` (`Checkout.tsx:183`, `:298`, `:374`); stalled `Alert tone="info"` (`:164`) | `Alert tone="ok"` (`:356`) | `billing`, `checkout` |
| `/settings/notifications` | `settings/notifications/page.tsx`, `NotificationChoices.tsx` | any signed-in user | `Button` primary Save (`NotificationChoices.tsx:138`) | busy, "Saving…" | shared EmptyState "There are no notification choices to make yet." (`:47`) | `Alert` (`NotificationChoices.tsx:127`); route 5 s timeout ends in the error boundary (`:21-30`) | `role=status` text with `data-saved` (`NotificationChoices.tsx:142`) | `notificationSettings` |
| `/settings/security` | `settings/security/page.tsx`, `SecuritySettings.tsx` | any signed-in user | `SubmitButton` primary "Turn on two-step sign-in" (`SecuritySettings.tsx:316`); recovery-code and enrolment steps have their own primaries (`EnrolmentSteps.tsx:243,253`, `NewRecoveryCodes.tsx:157,182,216`); password save is secondary (`PasswordSettings.tsx:128`) | `<Suspense>` fallbacks `role=status` "Loading…" / "Starting…" (`SecuritySettings.tsx:230,263`, `NewRecoveryCodes.tsx:176`); busy | n/a | `Alert` (`SecuritySettings.tsx:209,281,286`, `EnrolmentSteps.tsx:261`, `NewRecoveryCodes.tsx:193`) | `Alert tone="ok"` (`PasswordSettings.tsx:97`, `NewRecoveryCodes.tsx:152`); copy notices `role=status` (`EnrolmentSteps.tsx:194`, `RecoveryCodeList.tsx:92`) | `security`, `password` |
| `/problems/[id]` | `problems/[id]/page.tsx`, `components/problem/ProblemCard.tsx` | any signed-in side (developers reach it from Discover; staff from research review) | none | missing | unknown, candidate and rejected cards read the same: shared EmptyState "This problem is not available." (`:44`) | `(app)/error.tsx` | n/a | `problem` |

### 1.5 Staff admin console (`/admin`, 7 routes; `app/(admin)`, gate in `admin/layout.tsx` and `proxy.ts`)

Non-staff get the default 404 (section 0). Role gate (`components/AdminNav.tsx` `ADMIN_SECTIONS`): Research and Claims = staff admin; Moderation = staff admin and moderator; support has no section. A stale second factor shows `PageStepUp` instead of the page.

| Path | File | Who | Primary action | L | E | Err | S | Strings |
|---|---|---|---|---|---|---|---|---|
| `/admin` | `app/(admin)/admin/page.tsx` | staff (any role) | redirects to the first section the role may open; support: shared EmptyState `primary` (`:30`) | n/a | support role: "Your staff role has no console section yet." | `(admin)/error.tsx` | n/a | `admin` |
| `/admin/research` | `admin/research/page.tsx` | staff admin | `SubmitButton` primary start a run (`StartRun.tsx:156`) | busy; polling `role=status` (`StartRun.tsx:166`), refresh button (`:170`) | queue empty EmptyState `href="#run-niche"` (`:113`); no niches sentence (`:88`); runs and excerpts sections hidden when empty | `Alert` (`StartRun.tsx:135`); not-admin EmptyState (`:48`) | `router.refresh()` after a run (`StartRun.tsx:70`) | `adminResearch` |
| `/admin/research/candidates/[id]` | `research/candidates/[id]/page.tsx`, `Decision.tsx` | staff admin | `Button` primary Approve (`Decision.tsx:207`) and `<Link data-primary>` next (`:144`) | busy text (`:211`) | gone / not allowed: EmptyState (`page.tsx:56`) | `Alert` (`Decision.tsx:135`), `StepUp.tsx:74` | `Alert tone="ok"` (`Decision.tsx:106`) | `adminResearch` |
| `/admin/moderation` | `admin/moderation/page.tsx` | staff admin, moderator | `<Link data-primary>` "Review oldest" (`:76`; only on the open view when a case can be decided) | missing | EmptyState per view (`:93-95`): "No cases are waiting for a decision." / "No case has been decided yet." | not-allowed EmptyState (`:57`) | n/a | `adminModeration` |
| `/admin/moderation/cases/[id]` | `moderation/cases/[id]/page.tsx`, `CaseDecision.tsx` | staff admin, moderator | `Button` primary Approve (`CaseDecision.tsx:248`); `<Link data-primary>` next case (`:172`) | busy text (`:249`) | gone: EmptyState (`page.tsx:75`) | `role=status` result block (`CaseDecision.tsx:149`) | `router.refresh()` (`:124`, `:135`) | `adminModeration` |
| `/admin/claims` | `admin/claims/page.tsx` | staff admin | none (read only, `:29`) | missing | EmptyState per view with a link to another view (`:80-84`): "No claims are waiting for review." etc. | not-admin EmptyState (`:48`) | n/a | `adminClaims` |
| `/admin/claims/[id]` | `admin/claims/[id]/page.tsx` | staff admin | none (read only) | missing | gone: EmptyState (`:57`) | not-admin EmptyState (`:59`, `:64`) | n/a | `adminClaims` |

## 2. Emails a demo run puts in Mailpit

Provider: `EMAIL_PROVIDER=smtp` sends to Mailpit in dev and CI (`backend/.env.example:62-64`; adapters in `backend/src/bridge/notifications/email.py`).
Every send goes through the delivery ledger (`notifications/deliveries.py`). Paths below are under `backend/src/bridge/`.

| ID | Kind / tag | Subject | Trigger | Template or renderer | Parts |
|---|---|---|---|---|---|
| EM1 | `em1` | `Your proposal "{title}" is registered and sent to {N organisation(s)}` | A Pitch delivers a proposal to at least one E2 organisation; background task after the response (`proposals/pitch_router.py:160`, `notifications/em1.deliver`); once per Pitch | `notifications/templates/em1.txt.j2`, `em1.html.j2`; renderer `notifications/em1.py:121` | text + HTML |
| EM2 | `em2` | `Good news: {company_name} approved "{title}" to proceed (non-binding)` | Engagement enters `INTEREST_CONFIRMED` (`engagements/notify.py:368-370`, `_send_em2` `:280`); once per engagement | `notifications/templates/em2_subject.txt.j2`, `em2.txt.j2`, `em2.html.j2`; `notifications/em2.py:127` | text + HTML |
| N17 (developer notice, not numbered EM1..8) | `n17` | `{company} is interested in "{title}"` | An organisation expresses interest at stage 0 (`engagements/notify.py:364-366`, `_send_n17` `:298`); respects the developer's email preference | `notifications/templates/n17.txt.j2`, `n17.html.j2`; `notifications/n17.py:76` | text + HTML |
| EM3 (scout digest) | `em3` | `Scout digest: {N new matching proposal(s)} for {org}` | `scouts.scan` periodic job every 15 min (`jobs/scouts.py:39`) and `scouts.on_new`; to verified, opted-in Reviewer seats; max 10 items (`matching/digest.py:96-142`, send `:246`). The demo seed's "Telco A scout" step passes `runtime.email_provider` (`seed/demo/__init__.py:146-147`) | `notifications/templates/em3.txt.j2`, `em3.html.j2`; renderer `matching/digest.py` | text + HTML |
| EM7, developer daily nudge | `em7` | `Your day on Bridge ({date}): {summary}` | `reminders.dispatch`, cron every 15 min (`jobs/reminders.py:42`), one per developer per day at `send_after_hour` (spec default 07:30 EAT, `docs/platform/REQUIREMENTS.md` REQ-REM-01); `reminders/dispatch.py:273-328` | `reminders/templates/em7.html.j2`; plain text `reminders/render.py` `render_text`; composer `reminders/nudge.py:284-310` | text + HTML |
| EM7, organisation digest | `em7_org` | `{org}: progress digest, {date}` (daily) or `{org}: weekly progress digest, week of {date}` | `reminders.org_digest` job (`jobs/reminders.py:49`), daily or weekly per plan (`reminders/dispatch.py:355-393`) | same `reminders/templates/em7.html.j2` via `reminders/render.py`; content `reminders/org_digest.py:187-216` | text + HTML |
| Sign-up confirm | `auth.verify_email` | `Confirm your email for {product}` | Sign-up (`auth/service.py:214-215`); single-use link, no numeric code | wording `auth/emails.py` `verify_email` (marked `[[COPY-REVIEW]]`) | text only (`mailer.py:42`, `html=None`) |
| Sign-in link | `auth.login_link` | `Your {product} sign-in link` | "Email me a sign-in link" (`auth/service.py:352-353`) | `auth/emails.py` `login_link` | text only |
| Account exists | `auth.account_exists` | `You already have a {product} account` | Sign-up with an address that already has an account; at most one a day (`auth/service.py:232-234`) | `auth/emails.py` `account_exists` | text only |
| Security notice | `auth.security_notice` | `Security change on your {product} account` | Password changed, two-step sign-in on/off, new recovery codes (`auth/service.py:563,648,685,714`), social sign-in linked/unlinked (`auth/identities.py:236`) | `auth/emails.py` `security_notice` | text only |

Not built (no template or renderer in `backend/src/bridge`): EM4 Declined, EM5 Signature needed, EM6 Contact overdue, EM8 Verification result (REQ-NOT-05, `docs/platform/REQUIREMENTS.md` line 143, status TODO). A demo run cannot produce them.
Also present but not called from the platform: `reminders/templates/reminder_email.html.j2` with `reminders/compose.py` (port of the legacy local reminder; no caller outside its own module).
The auth emails are plain text only (no HTML part); EM1, EM2, N17, EM3 and EM7 send text and HTML. No email carries a numeric one-time code.

## 3. Shared layer

### 3.1 `components/ui/*`

| File | What it is |
|---|---|
| `Alert.tsx` | Notice with icon and words; tones `error` (role alert), `info`, `ok` (role status); border and wash colours mixed from tokens. |
| `Button.tsx` | `Button` with variants `primary` / `secondary` / `link`, `busy` (aria-disabled, stays focusable); exports `buttonClass`, `primaryMark` (adds `data-primary`), `textLinkClass`, `standaloneLinkClass`. |
| `ButtonLink.tsx` | `next/link` styled as a button, same variants; separate module to keep `next/link` out of client bundles. |
| `Form.tsx` | `Form` (method post, `noValidate`, `data-hydrated`) and `SubmitButton` (disabled until hydrated). |
| `Field.tsx` | Label, hint, error wrapper plus the shared input class; `FieldControlProps`. |
| `TextField.tsx` | Labelled text input. |
| `TextAreaField.tsx` | Labelled textarea with optional meter line. |
| `SelectField.tsx` | Labelled native select. |
| `PasswordField.tsx` | Password input with show/hide button. |
| `OtpInput.tsx` | One-time code input; `normaliseCode`. |
| `Checkbox.tsx` | Checkbox whose whole row (44 px) toggles it. |
| `RadioGroup.tsx` | Fieldset of radio rows with hint text. |
| `AccountUsername.tsx` | Hidden `autocomplete="username"` field for password forms. |
| `cn.ts` | Class-name joiner. |
| `icons.tsx` | The authored 20 px icon set (nav, eye, etc.); re-exports status icons. |
| `status-icons.tsx` | Icons used by client components (alert, check, clock, info, lock, send) and the base `Icon`. |

Not in `components/ui`: no Card, Badge/Chip, Dialog/Modal, EmptyState, Skeleton/Spinner, Toast, Table/List row, Tabs, Heading, or DescriptionList component. The nearest are in other folders (`app/(app)/org/EmptyState.tsx`, `components/tracker/Chip.tsx`, `app/(admin)/admin/ViewTabs.tsx`).

### 3.2 Shells and navigation

| Component | Role |
|---|---|
| `components/SignedInShell.tsx` | Signed-in frame: `TopBar` + `AccountMenu`, optional portal nav, `<main id="main">`; `wide` prop picks full width vs a 36 rem column; pads for the fixed tab bar under 1024 px. |
| `components/TopBar.tsx` | Skip link, working name link, one slot on the right. Not sticky. |
| `components/DevNav.tsx` | Developer sections Home, Discover, My ideas, Engagements, Companies: bottom tabs under 1024 px, left rail above. |
| `components/OrgNav.tsx` | Organisation sections Home, Inbox, Engagements; carries `?org=`. |
| `components/AdminNav.tsx` | Staff sections Research, Moderation, Claims, filtered by staff role. `app/(admin)/admin/AdminShell.tsx` wraps it in `SignedInShell`. |
| `components/AccountMenu.tsx` | Avatar menu (client): Plan and billing, Notifications, Help, Sign out. Popover is a hand-rolled bordered box (`:93`). |
| `components/AuthShell.tsx` | Signed-out frame: top bar, one column, "how it works" side panel (`rounded-panel bg-jacaranda-wash`) from 1024 px (always on the landing page). |
| `components/ErrorScreen.tsx` | Route-group error UI, with its own copy of the primary button classes (`:8`) instead of importing `Button`. `LazyErrorScreen.tsx` code-splits it. |
| Others | `app/(public)/verify/VerifyShell.tsx` (a second, separate side-panel layout for `/verify`), `components/HomeSummary.tsx` (org home greeting + 2FA status), `components/BridgeLine.tsx`, `ClientStrings.tsx`, `IntlScope.tsx`, `SignOutButton.tsx`, `QrCode.tsx`, icon sets `admin-icons.tsx`, `discover-icons.tsx`, `org-icons.tsx`, `components/tracker/*` (22 files) and `components/problem/*`. |

### 3.3 Tokens (`app/globals.css`, 170 lines)

| Group | Values |
|---|---|
| Colours (`:root`, mapped to Tailwind via `@theme inline`) | `--paper #f5f7f3`, `--ink #16232f`, `--ink-soft #4a5866`, `--jacaranda #5b3e96` (the only accent), `--jacaranda-wash #ece6f6`, `--line #c9d1c8`, `--ok #1f6b47`, `--error #a8241b`, `--field #ffffff`, `--on-accent #fff`, `--on-ok #fff`. Light only (`color-scheme: light`). No warning colour, no dark mode. |
| Focus | `--focus-ring: 2px solid var(--jacaranda)`, `--focus-offset: 2px`, applied to `:focus-visible`. |
| Font | `--font-sans` system stack, no web fonts. |
| Radii | `--radius-control 10px`, `--radius-panel 16px` (the comment says nothing else is rounded; `rounded-full` and `rounded-[8px]` also appear, see 4.6). |
| Type scale | `--text-sm` .875 / `base` 1 / `lg` 1.25 / `xl` 1.5625 / `2xl` 1.9375 / `3xl` 2.4375 rem, each with a line height. Base styles set `h1-h3` weight 600, `text-wrap: balance`. |
| Base rules | `scroll-padding-block` for focus; extra bottom padding when `[data-tab-bar]` or `[data-action-bar]` is present; link underline offset; selection and caret colours. |
| Utilities and motion | `@utility code-figures` (tabular figures); `.bridge-draw` keyframes (landing only); a `prefers-reduced-motion` reset. |
| Not defined | spacing scale, shadows, z-index, breakpoints (Tailwind defaults), border-width or divider tokens, status-tone tokens beyond `ok`/`error`. |

### 3.4 Inner `<Suspense>` boundaries (the only loading UI besides busy text)

`Editor.tsx:534` (status text), `:576`, `:589` (null); `ProblemPicker.tsx:47` (null); `SecuritySettings.tsx:214` (null), `:230`, `:263` (status text); `NewRecoveryCodes.tsx:176`; `ErrorNotice.tsx:33` (null); `LazyErrorScreen.tsx:12` (null); `components/tracker/Actions.tsx:222` ("Working…").

## 4. Repeated one-off patterns

Class strings are abbreviated only where noted. Counts are from `grep` over non-test `.tsx` in `app/` and `components/`.

### 4.1 Cards and bordered boxes

| Class string | Instances (file:line) |
|---|---|
| `rounded-panel border border-line bg-field` (+ padding) | `app/(app)/org/inbox/matches/ScoutMatches.tsx:75`; `app/(app)/dev/ideas/editor/AssistantPanel.tsx:245`; `app/(admin)/admin/research/candidates/[id]/page.tsx:127`; `app/(admin)/admin/moderation/cases/[id]/page.tsx:200` |
| `rounded-panel border border-line bg-paper p-6` (dialog box) | `AssistantPanel.tsx:326`; `app/(app)/dev/ideas/[id]/WithdrawTag.tsx:79`; `app/(app)/dev/ideas/[id]/DeleteIdea.tsx:68` |
| `rounded-panel bg-jacaranda-wash p-6` (wash panel, no border) | `components/AuthShell.tsx:36`; `app/(public)/verify/VerifyShell.tsx:24`; `app/(admin)/admin/research/page.tsx:77` |
| `rounded-control border border-line bg-field` | `app/(app)/org/inbox/[proposalId]/FullProposal.tsx:56` (iframe), `:158`; `components/tracker/EngagementScreen.tsx:245`; `components/AccountMenu.tsx:93` (popover) |
| `rounded-control p-4` + wash or `border border-line` | `AssistantPanel.tsx:215` |
| `border border-line bg-field` (square) | `app/(app)/settings/security/RecoveryCodeList.tsx:74`; `components/QrCode.tsx:18` (white) |
| Left-rule callouts (`border-l-2` / `border-l-4` with `border-jacaranda`, `-wash`, `-line`, `-error`, `-ok`) | `ScoutScreen.tsx:124`; `ScoutPreview.tsx:46`; `MatchParts.tsx:34`; `org/inbox/page.tsx:147`; `FullProposal.tsx:75`; `ProjectRow.tsx:44,52`; `ProblemRow.tsx:77`; `ProfilingToggle.tsx:55`; `RecommendedForYou.tsx:115`; `Review.tsx:171`; `AssistantPanel.tsx:295`; `DetailsStep.tsx:34`; `app/(app)/dev/ideas/[id]/page.tsx:218`; `research/Decision.tsx:182`; `moderation/CaseDecision.tsx:225`; `app/(public)/verify/FileCheck.tsx:113`; `VerifyRecord.tsx:31`; `components/tracker/WhoseTurn.tsx:41`; `components/problem/Citations.tsx:38` |
| Section divider `border-t border-line pt-N` (used as "card" separators) | 50 lines, for example `app/(app)/dev/page.tsx:131`, `app/(app)/settings/security/PasswordSettings.tsx:89`, `app/(public)/help/page.tsx:43`, `app/(admin)/admin/research/candidates/[id]/page.tsx:152`, `components/tracker/Deal.tsx:70,88`, `EngagementScreen.tsx:227`; the full list is in 4.7 |

Totals: `rounded-panel` 10 uses (4 cards, 3 dialogs, 3 wash panels); bordered `rounded-control` boxes 7; left-rule callouts 20.

### 4.2 Chips, badges, status pills

No shared component. Status = icon + words + colour, hand-built each time.

| Pattern / class | Instances (file:line) |
|---|---|
| `inline-flex items-center gap-1.5 font-medium` + tone (idea status) | `app/(app)/dev/ideas/IdeaStatusBadge.tsx:22` (`data-status`); `app/(app)/dev/ideas/[id]/Pitches.tsx:114` (`data-status`, `text-sm`) |
| `flex items-start gap-1.5 text-sm font-medium` + tone (verification badge) | `app/(app)/dev/companies/VerificationBadge.tsx:20` (`data-badge`) |
| `inline-flex ... text-sm font-semibold` tracker chip via `Chip`/`ChipMark` | `components/tracker/Chip.tsx:71-78` (`data-chip={kind}`); used in `WhoseTurn.tsx`, `Endorsements.tsx`, `Deal.tsx`, `Stepper.tsx`, `EngagementRow.tsx` |
| Filled pill `rounded-control bg-jacaranda px-2 py-0.5 text-sm font-semibold text-on-accent` | `components/tracker/EngagementRow.tsx:34` (`data-chip="turn"`) |
| `rounded-control border px-2 py-0.5 text-sm font-semibold` | `app/(app)/dev/ideas/editor/AssistantPanel.tsx:236` (`data-chip`) |
| `rounded-control bg-jacaranda-wash px-2.5 py-1 text-sm font-semibold text-jacaranda` | `app/(app)/billing/upgrade/page.tsx:113` (`data-simulated`) |
| `rounded-control border border-line px-2.5 py-1 text-sm font-medium text-ink-soft` | `app/(app)/billing/SamplePrices.tsx:8` |
| Stage chip (link or span) | `app/(app)/org/StageChip.tsx:54,63` (`data-chip="stage"`) |
| Why / trend / pursuit chips | `app/(app)/dev/discover/Chips.tsx:17` (`data-chip="why"`), `:33` (`data-badge`); `RecommendedForYou.tsx:107` (`data-chip="pursuit"`) |
| Fit meter (`rounded-full` bar) | `app/(app)/org/inbox/matches/MatchParts.tsx:13-15` (`data-chip="fit"`) |
| Other `data-chip` | `IdeaRow.tsx:36`; `app/(admin)/admin/research/Sections.tsx:46,51`; `app/(admin)/admin/moderation/CaseRow.tsx:71`; pitch outcome `app/(app)/dev/ideas/[id]/pitch/page.tsx:266,271` (`data-outcome`) |

Total: 18 `data-chip` / `data-badge` markers, 5 more status/outcome/simulated markers, 7 distinct class recipes.

### 4.3 Tables and lists of rows

There is no `<table>` anywhere. Rows are `<ul>`/`<ol>` of `<article>`/`<li>` with a top border and a bottom border on the list.

| Class string | Instances (file:line) |
|---|---|
| List `border-b border-line` + row `border-t border-line py-5` with a stretched-link title (`after:absolute after:inset-0`) | `app/(app)/dev/ideas/IdeaRow.tsx:23`; `components/tracker/EngagementRow.tsx:17`; lists at `dev/page.tsx:83,100,118`, `dev/ideas/page.tsx:56`, `components/tracker/EngagementList.tsx:36` |
| Row `border-t border-line py-5` (other rows) | `app/(app)/org/inbox/InboxRow.tsx:21`; `org/inbox/matches/MatchRow.tsx:22`; `dev/discover/ProblemRow.tsx:57`; `ProjectRow.tsx:29` (grid); `dev/companies/OrgRow.tsx:17` (`py-4`) |
| Ordered lists `border-b border-line` | `DiscoverList.tsx:46,73,101`; `RecommendedForYou.tsx:53`; `WhoHasSeen.tsx:34` |
| `<li ... border-t border-line py-N first:border-t-0 first:pt-0` (admin) | `admin/research/Sections.tsx:34,71,134`; `moderation/CaseRow.tsx:46`; `claims/ClaimRow.tsx:40`; `claims/[id]/page.tsx:207` |
| Smaller row lists | `ScoutPreview.tsx:39`; `ScoutMatches.tsx:81`; `ProblemPanels.tsx:154`; `WhoHasSeen.tsx:36`; `Pitches.tsx:100`; `PitchForm.tsx:443-463`; `components/tracker/HistoryList.tsx:66`; `Deal.tsx:116,188,220` |
| Tab strips `nav ... border-b border-line` | `org/inbox/InboxTabs.tsx:24`; `dev/discover/DiscoverControls.tsx:26`; `admin/ViewTabs.tsx:18`; `components/tracker/EngagementScreen.tsx:131` |
| Label/value grid (`<dl class="grid gap-x-8 gap-y-4 border-t border-line pt-N sm:grid-cols-[minmax(9rem,auto)_1fr]">`) with a local `Row` helper | `Row` defined 8 times: `org/inbox/[proposalId]/TeaserDetails.tsx:61`; `dev/companies/[orgId]/page.tsx:78`; `dev/ideas/[id]/page.tsx:331`; `pitch/PitchForm.tsx:303`; `admin/research/candidates/[id]/page.tsx:173`; `admin/claims/[id]/page.tsx:242` (`sm:grid-cols-[14rem_1fr]`, `:237`); `verify/VerifyRecord.tsx:89`; `components/problem/ProblemCard.tsx:72`. `<dl>` grids at `companies/[orgId]/page.tsx:49`; `ideas/[id]/page.tsx:176,230,281`; `candidates/[id]/page.tsx:101`; `ProblemCard.tsx:38` |

Totals: 41 row-border lines; 8 `Row` helpers; 4 tab-strip implementations (5 uses).

### 4.4 Empty states

Sentence + one action. Shared component exists but is used 60 times from a path under `org/`; 12 hand-rolled copies and 2 local `Empty` components remain.

| Variant | Instances (file:line) |
|---|---|
| Shared `EmptyState` (`app/(app)/org/EmptyState.tsx:21`, `flex flex-col items-start gap-3 border-t border-line pt-6`, `max-w-[60ch]`) | 60 `<EmptyState` uses across `org/`, `dev/discover/DiscoverList.tsx`, `RecommendedForYou.tsx`, `niches/page.tsx:74`, `billing/page.tsx`, `billing/upgrade/page.tsx`, `settings/notifications/page.tsx:47`, `problems/[id]/page.tsx:44`, and every admin page |
| Hand-rolled `data-empty-state` (12) | `app/(app)/dev/engagements/page.tsx:39` (`gap-3`, `max-w-[52ch]`); `app/(app)/dev/page.tsx:70`; `app/(app)/dev/ideas/page.tsx:64` (`gap-5`); `app/(app)/dev/companies/DirectoryResults.tsx:92`; `dev/ideas/editor/ProblemPanels.tsx:178` (`pt-4`); `dev/ideas/editor/EditorScreen.tsx:43`; `dev/ideas/[id]/page.tsx:67`; `dev/ideas/[id]/WhoHasSeen.tsx:27` (`mt-4 pt-4`); `dev/ideas/[id]/Pitches.tsx:76` (`mt-4 pt-4`); `dev/ideas/[id]/pitch/page.tsx:161`; `components/tracker/Refused.tsx:14` (`data-refusal`); `components/tracker/EngagementScreen.tsx:197` (no border) |
| Local `Empty` components | `app/(app)/dev/ideas/[id]/pitch/page.tsx:159` and `app/(app)/dev/companies/DirectoryResults.tsx` (`Empty` export near `:90`); used by `companies/[orgId]/page.tsx:70` |
| Sentence-only empties (no action) | `ideas/[id]/page.tsx:228` ("No full details yet."), `:320`; `admin/research/page.tsx:88` (`start.noNiches`); `DirectoryResults`/`Pitches` inner messages |

Total: 13 `data-empty-state` lines (12 hand-rolled plus the shared one at `EmptyState.tsx:21`), 60 shared uses, 2 local components.
"No ..." sentences in `locales/en.json` (selection): `devHome.empty`, `ideas.empty`, `tracker.emptyOrg`, `tracker.documents.empty`, `inbox.emptyE2`, `scoutMatches.emptyNoMatches`, `companies.emptyFiltered`, `pitch.emptyAll`, `adminClaims.empty.*`, `adminModeration.emptyOpen`, `adminResearch.queue.empty`.

### 4.5 Loading, busy and skeleton text

No skeletons. No spinner component. One animation: `motion-safe:animate-pulse` on a clock icon (`app/(app)/billing/upgrade/Checkout.tsx:157`).

| Pattern | Instances (file:line) |
|---|---|
| Button label swap when busy (`busy ? t("...ing") : t("...")`) | about 29 uses, for example `LoginForm.tsx:115`, `SignupForm.tsx:289`, `MfaForm.tsx:105`, `FileCheck.tsx:90`, `Review.tsx:234`, `PitchForm.tsx:294`, `DeleteIdea.tsx:89`, `WithdrawTag.tsx:96`, `CaseDecision.tsx:249`, `Decision.tsx:211`, `StepUp.tsx:89`, `ProblemPanels.tsx:141` |
| `<Suspense fallback={<p role="status" className="text-ink-soft">...}>` | `SecuritySettings.tsx:230,263`; `NewRecoveryCodes.tsx:176`; `Actions.tsx:222` (`<p className="text-ink-soft">`, no role); `Editor.tsx:536` |
| `role="status"` live text | `LinkSignIn.tsx:161,177`; `Attachments.tsx:144`; `AssistantPanel.tsx:257`; `EnrolmentSteps.tsx:194`; `RecoveryCodeList.tsx:92`; `Checkout.tsx:156`; `StartRun.tsx:166`; `CaseDecision.tsx:149`; `FileCheck.tsx:94`; `ProfilingToggle.tsx:58`; `PitchForm.tsx:218`; `NotificationChoices.tsx:142`; `Editor.tsx:645` |

Totals: 18 `role="status"` elements, 2 `aria-live` elements (`NichePicker.tsx:87`, `PitchForm.tsx:282`), 4 status-text `<Suspense>` fallbacks, 11 `<Suspense>` in all, 0 `loading.tsx`.

### 4.6 Saved confirmations and toasts

No toast component. Confirmations are inline.

| Pattern | Instances (file:line) |
|---|---|
| `<Alert tone="ok">` | `ExpressInterest.tsx:153`; `NichePicker.tsx:128`; `AssistantPanel.tsx:262`; `dev/ideas/[id]/page.tsx:104`; `dev/ideas/page.tsx:49`; `NewRecoveryCodes.tsx:152`; `PasswordSettings.tsx:97`; `Checkout.tsx:356`; `research/Decision.tsx:106`; `signup/check-email/CheckEmail.tsx:53`; `components/tracker/ShareTier2.tsx:88` |
| Green text `role="status"` with icon | `NotificationChoices.tsx:142` (`data-saved`); `Editor.tsx:645` (autosave); `EnrolmentSteps.tsx:197` |
| Redirect as the confirmation | `Review.tsx:127` (`?published=1`); `DeleteIdea.tsx:50` (`?removed=`); `ScoutForm.tsx:170`; `ExpressInterest.tsx:121` |
| `router.refresh()` as the confirmation | `Actions.tsx:126`; `ShareTier2.tsx:63`; `WithdrawTag.tsx:52`; `CaseDecision.tsx:124`; `StartRun.tsx:70` |
| Error `<Alert>` (default tone) | 74 `<Alert` in total |

### 4.7 Confirmation dialogs

All three are native `<dialog>` + `showModal()`; each re-implements the box (`m-auto w-[calc(100%-2rem)] max-w-md|lg rounded-panel border border-line bg-paper p-6 text-ink`), a cancel `Button` and a confirm button with busy text. No `window.confirm`.

| Instance | file:line |
|---|---|
| Delete or hide idea (danger outline trigger `DANGER_OUTLINE` `DeleteIdea.tsx:18`) | `app/(app)/dev/ideas/[id]/DeleteIdea.tsx:62` (trigger `:59`) |
| Withdraw a pitch | `app/(app)/dev/ideas/[id]/WithdrawTag.tsx:70` (`showModal` `:63`) |
| Turn on the writing assistant (consent) | `app/(app)/dev/ideas/editor/AssistantPanel.tsx:316` (`showModal` `:197`; `max-w-lg`, with a `backdrop:` tint) |

Related: a danger-outline button class is also defined at `components/tracker/Actions.tsx:31` (`border-error`) and `DeleteIdea.tsx:18`.

### 4.8 Section headings and page titles

| Pattern | Instances |
|---|---|
| Page title `<h1 className="text-xl text-ink lg:text-2xl">` (sometimes with `[overflow-wrap:anywhere]`, `focus:outline-none`, `tabIndex={-1}`) | 55 `<h1>`; about 52 use the `text-xl ... text-ink lg:text-2xl` recipe (every page file, plus `LinkSignIn.tsx`, `Refused.tsx`, `EngagementScreen.tsx`, `ProblemCard.tsx`) |
| Section title `<h2 className="text-lg text-ink">` | 90 classed `<h2>`/`<h3>`; 60+ use exactly `text-lg text-ink`. Examples: `dev/page.tsx:80,97,115`; `org/page.tsx:76`; `ideas/[id]/page.tsx:172,219,275`; `billing/page.tsx:93`; `SecuritySettings`/`security/page.tsx:30`; `research/page.tsx:78,93,111`; `Sections.tsx:35,123`; `claims/[id]/page.tsx:178,202,232`; `cases/[id]/page.tsx:127,146,156`; `components/tracker/Deal.tsx:37`, `Endorsements.tsx:20`, `HistoryList.tsx:47`, `Actions.tsx:162`, `Tier2Section.tsx:41,59`, `ShareTier2.tsx:84`, `EngagementList.tsx:33`, `EngagementRow.tsx:18`, `EngagementScreen.tsx:209`; `help/page.tsx:44`; `FileCheck.tsx:66`; `VerifyShell.tsx:25`; `AuthShell.tsx:43` |
| Smaller headings `text-base font-semibold text-ink` | `dev/page.tsx:132`; `FullProposal.tsx:155,185`; `Sections.tsx:129`; `Editor.tsx:437,522`; `Review.tsx:144,160`; `SecuritySettings.tsx:226`; `Endorsements.tsx:43`; `Deal.tsx:89`; `EngagementScreen.tsx:228` |
| Eyebrow / small label `text-sm font-medium text-ink-soft` | `Checkout.tsx:260`; `candidates/[id]/page.tsx:134`; `VerifyRecord.tsx:32`; `<dt>` in every `Row` |
| Back link `<p className="-mt-2 mb-4">` + `standaloneLinkClass` | 11 copies: `companies/[orgId]/page.tsx:42`; `niches/page.tsx:51`; `EditorScreen.tsx:57`; `ideas/[id]/page.tsx:88`; `pitch/page.tsx:142`; `billing/upgrade/page.tsx:53`; `problems/[id]/page.tsx:33`; `candidates/[id]/page.tsx:37`; `cases/[id]/page.tsx:55`; `claims/[id]/page.tsx:39`; `components/tracker/EngagementScreen.tsx:86` |

### 4.9 Other duplicated recipes

| Recipe | Instances |
|---|---|
| Primary button class rebuilt outside `Button` | `components/ErrorScreen.tsx:8` (own copy); `<Link data-primary className={buttonClass("primary","no-underline")}>` in `org/page.tsx:82`, `billing/page.tsx:186`, `Checkout.tsx:360`, `CaseDecision.tsx:172`, `Decision.tsx:144`, `moderation/page.tsx:76`, `EmptyState.tsx:24`; plain `<button data-primary>` at `verify/page.tsx:53`, `DirectoryFilters.tsx:52` |
| `rounded-full` | `MatchParts.tsx:14,15`; `IdeaRow.tsx:37` (unread dot); `settings/security/Steps.tsx:45`; `billing/page.tsx:144,148,179`; `Checkout.tsx:275`; `components/tracker/Stepper.tsx:34`; `AccountMenu.tsx:83` (10 total; Steps, plan ladder and tracker stepper each redraw a rail with a dot) |
| Stepper / rail | `app/(app)/dev/ideas/editor/Stepper.tsx`; `components/tracker/Stepper.tsx`; `settings/security/Steps.tsx`; `billing/page.tsx:139-156` |
| Upload label styled as a button | `app/(app)/dev/ideas/editor/Attachments.tsx:163` |

## 5. Counts

| Measure | Count |
|---|---|
| Routes (`page.tsx`) | 42 |
| Public | 10 |
| Developer (`/dev`) | 12 |
| Organisation (`/org`) | 8 |
| Either signed-in side (`/billing` x2, `/settings` x2, `/problems`) | 5 |
| Staff admin (`/admin`) | 7 |
| Routes with a page-level loading state | 0 (`loading.tsx` files: 0) |
| Route-group `error.tsx` files | 3 (`not-found.tsx`: 0, `global-error.tsx`: 0) |
| Routes with no primary action | `/legal/terms`, `/help`, `/signup/check-email`, `/dev/discover`, `/dev/companies/[orgId]`, `/dev/engagements`, `/org/inbox` (list), `/org/engagements` (list), `/problems/[id]`, `/admin/moderation` (none unless a case can be decided), `/admin/claims`, `/admin/claims/[id]` |
| Hard-coded English literals found in JSX | 0 |
| Emails produced by code | 10 kinds: EM1, EM2, N17, EM3, EM7 developer, EM7 organisation, and four auth kinds (`auth.verify_email`, `auth.login_link`, `auth.account_exists`, `auth.security_notice`) |
| Emails in the EM1..EM8 series not built | 4 (EM4, EM5, EM6, EM8) |
| `components/ui` components | 16 files (11 UI components, `cn`, two icon files, `AccountUsername`) |
| `<Alert` uses | 74 |
| Shared `<EmptyState` uses / hand-rolled `data-empty-state` / local `Empty` components | 60 / 12 (plus the shared one at `EmptyState.tsx:21`) / 2 |
| Native `<dialog>` confirmations / `window.confirm` | 3 / 0 |
| `rounded-panel` uses (cards 4, dialogs 3, wash panels 3) | 10 |
| Bordered `rounded-control` boxes | 7 |
| `rounded-full` uses | 10 |
| Left-rule callouts (`border-l-2` / `border-l-4`) | 20 |
| Chip/badge markers (`data-chip`, `data-badge`) / status-outcome markers | 18 / 5 |
| Row-list border lines (`border-t border-line py-`, `border-b border-line"`) | 41 |
| Local `Row` (label/value) helpers | 8 |
| Tab strips (`nav ... border-b border-line`) | 4 implementations (`InboxTabs`, `DiscoverControls`, `ViewTabs`, `EngagementScreen`), 5 uses (`ViewTabs` is used by Moderation and Claims) |
| Section dividers `border-t border-line pt-N` | 50 |
| `<table>` elements | 0 |
| `role="status"` elements / `aria-live` elements | 18 / 2 |
| `<Suspense>` boundaries / with status-text fallback | 11 / 4 |
| `<h1>` / classed `<h2>`,`<h3>` | 55 / 90 |
| Back-link `-mt-2 mb-4` copies | 11 |
| Skeleton, spinner, toast components | 0 |
