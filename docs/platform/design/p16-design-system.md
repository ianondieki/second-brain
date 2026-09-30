# P16 design system — one product, not a patchwork (REQ-UX-01..04, prototype part)

Written by the orchestrator with the `frontend-design` and `impeccable` skills (mode: **Operate**; `/help` and
`/legal/terms` are Read) before the P16 polish. It extends `phase1-auth-ui.md`; it does not replace it. Precedence:
`CLAUDE.md`, `docs/spec/07` and `docs/spec/04` §4.6 win over this file and over any skill advice (system font stack,
≤5 nav items, one primary action, 360 px first, WCAG 2.2 AA, ≤150 KB gzipped JS per route). No new UI or CSS library:
Tailwind 4 and the tokens in `frontend/app/globals.css` only. Copy stays in `frontend/locales/*.json`,
`[[COPY-REVIEW]]`.

## Evidence (tour of 2026-09-30 on a clean `make demo`, 39 screens × 375/1440 px)

The incumbent world is sound and stays: cool paper, one jacaranda accent, ink text, hairlines, no shadows, one
system sans, sentence case. axe found no serious or critical violation and no screen scrolls sideways at 375 px. What
reads as a patchwork is **drift between screens built by different tasks**:

| Drift | Where (examples) | Class |
|---|---|---|
| Four hand-rolled tab bars with different padding, weight and gaps | `org/inbox/InboxTabs.tsx`, `admin/ViewTabs.tsx`, `dev/discover/DiscoverControls.tsx`, `components/tracker/EngagementScreen.tsx` | one-off implementation |
| Three copies of the portal nav (items, active bar, hover wash) | `DevNav.tsx`, `OrgNav.tsx`, `AdminNav.tsx` | one-off implementation |
| Status shown four ways: filled pill ("Your turn"), icon + coloured bold text, icon + ink bold text, plain soft text | Home, tracker, moderation rows, ideas list | missing component |
| A 3–4 px coloured left rule as a callout, next to the bordered `Alert` | `tracker/WhoseTurn.tsx`, `dev/ideas/[id]/page.tsx`, `editor/DetailsStep.tsx`, `editor/Review.tsx`, `verify/VerifyRecord.tsx`, `verify/FileCheck.tsx`, `admin/moderation/cases/[id]` | conceptual mismatch (two notice patterns) |
| Section headings with a rule on some pages, without on others; the rule belongs to lists, not headings | Home vs tracker ("Your actions", "Contact person") | local defect |
| Label/value lists with different label column widths on one page | tracker Contact person vs Agreement | missing component |
| An eyebrow label above row titles ("Problem", "Proposal") | `admin/moderation` rows | refused pattern (craft floor) |
| A red outline "Withdraw" button that is not a Button variant | tracker actions | missing variant |
| No loading state anywhere: no `loading.tsx`, dynamic routes are not partially prefetched | every route | missing state |
| The error boundary re-implements the primary button's classes | `components/ErrorScreen.tsx` | kept on purpose (bundle size), documented |

## Token system (kept, extended)

Colour: unchanged hex values (`--paper #F5F7F3`, `--ink #16232F`, `--ink-soft #4A5866`, `--jacaranda #5B3E96`,
`--jacaranda-wash #ECE6F6`, `--line #C9D1C8`, `--ok #1F6B47`, `--error #A8241B`, `--field #FFFFFF`). Added, only
where a colour-mix was repeated inline:

| Token | Value | Role |
|---|---|---|
| `--accent-strong` | `color-mix(in oklab, var(--jacaranda) 84%, var(--ink))` | hover/pressed accent (was inline in 7 places) |
| `--wash-soft` | `color-mix(in oklab, var(--jacaranda-wash) 55%, var(--paper))` | nav hover, selected rows |
| `--error-wash` / `--ok-wash` | `color-mix(in oklab, var(--error\|--ok) 7%, var(--field))` | error and success notice backgrounds |
| `--error-line` / `--ok-line` / `--accent-line` | the 35–45% mixes used by `Alert` | notice borders |
| `--scrim` | `color-mix(in oklab, var(--ink) 45%, transparent)` | the one dialog backdrop |
| `--shadow-overlay` | `0 12px 28px -12px rgb(22 35 47 / 0.28), 0 2px 6px -2px rgb(22 35 47 / 0.12)` | **the only elevation**: popovers and dialogs (account menu, filters, confirm dialog). Offset plus soft blur, tinted from ink. Nothing on the page itself casts a shadow. |

Radius: `--radius-control` 10 px (inputs, buttons, notices, menus), `--radius-panel` 16 px (the one side panel per
screen, dialogs), `rounded-full` only for the avatar and the one solid badge. Nothing else is rounded.

Type (one system sans, 1.25 scale on 16 px, unchanged): each role has one size, set in the component that owns it.

| Role | Size / weight | Owner |
|---|---|---|
| Page title (h1) | `text-xl` (25) at 360 px, `lg:text-2xl` (31); 600 | `PageHeader` |
| Section title (h2) | `text-lg` (20); 600 | `Section` |
| Row title (h3 or the row link) | `text-base` (16); 600 | `RowList` rows |
| Body | `text-base`, line-height 1.6, measure ≤ 70ch | — |
| Meta, hints, badges | `text-sm` (14); 400 (meta) or 600 (badge) | `Meta`, `Badge` |

Spacing (Tailwind's 4 px scale, used in these steps only): 4 / 8 / 12 (inline gaps), 16 (heading → its content, row
title → meta), 20 (row padding), 24 (fields in a form), 40 (page header → first section), 48 (between sections).
Tighter inside groups, wider between them; more space above a heading than below it.

## Layout

Unchanged frame: top bar (working name, one control), portal nav (bottom tabs < 1024 px, left rail ≥ 1024 px), one
content column (`max-w-xl` for forms and summaries, full width up to `max-w-6xl` for lists and directories), 16 px
gutters at 360 px.

```
360 px                                  ≥1024 px
+----------------------------------+    +-------+----------------------------------------------+
| Bridge (working name)   (o) v    |    | Bridge (working name)                   (o) Account v |
|----------------------------------|    +-------+----------------------------------------------+
| < Back link                      |    | Home  | < Back link                                  |
| Page title                       |    | ...   | Page title                   [Primary action]|
| One-sentence lead                |    |       | One-sentence lead                            |
| [Primary action, full width]     |    |       | [Whose turn / notice]                        |
| Section title                    |    |       | Section title                     secondary >|
| ─────────────────────────────    |    |       | ──────────────────────────────────────────── |
| Row title (link)                 |    |       | Row title (link)                             |
| meta · meta        (Badge)       |    |       | meta   meta   (Badge) (Why chip)             |
| ─────────────────────────────    |    |       | ──────────────────────────────────────────── |
+----------------------------------+    +-------+----------------------------------------------+
| Home  Discover  Ideas  Eng.  Co. |
+----------------------------------+
```

Left-aligned throughout; numbers in tables right-aligned with tabular figures.

## Components (one pattern each; `frontend/components/ui/`)

| Pattern | Component | Rules |
|---|---|---|
| Buttons | `Button`, `ButtonLink` (+ variant `danger`) | primary (one per screen, `data-primary`), secondary, danger (error text and border; never filled), link. 48 px tall; link 44 px. Busy = `aria-disabled`, focusable. |
| Page header | `PageHeader` | optional back link, h1, one-sentence lead, optional action slot (the primary action). |
| Sections | `Section` | h2 + optional one-line description + optional secondary link at the end of the heading row. No rule under the heading. |
| Lists of things | `RowList`, `Row` | hairline above the first row and between rows; each row: title (a link when the row has a page), one meta line, at most two badges (spec 07 item 2), an optional right-aligned figure. |
| Label/value | `DescriptionList` | `<dl>`; label column 11rem from 640 px, stacked below; tabular figures for amounts and dates. |
| Status | `Badge` | icon + words + tone (`accent`, `ok`, `error`, `neutral`); `solid` only for the one "Your turn"/"Needs you" marker. Never colour alone. |
| Notices | `Alert` (dynamic, announced) and `Callout` (static) | both: 1 px tone border, tone wash, icon, words, `rounded-control`. Replaces every coloured left rule. The whose-turn banner is a `Callout` with a title. |
| Tabs | `TabNav` | links with `aria-current="page"`, 44 px targets, 2 px jacaranda underline on the current tab, scrolls sideways inside itself at 360 px. |
| Portal nav | `PortalNav` | one implementation behind `DevNav`, `OrgNav`, `AdminNav`. |
| Empty states | `EmptyState` | `data-empty-state`, exactly one sentence and one action link (AC-UX-5). |
| Loading | no route-level `loading.tsx`; `LinkPending` in navigation links; the in-page `<Suspense>` status sentences | Pages render in one server pass. A route skeleton was built and measured in P16 part B, then removed: React holds a revealed Suspense fallback for at least ~300 ms and the API answers well inside that, so Lighthouse mobile LCP went from 1.6–1.7 s to 2.4 s on `/dev`, 1.7 to 2.4 s on `/dev/discover` and 1.6 to 2.3 s on the tracker, and the MFA-pending redirect became a 200. In-app navigation shows `LinkPending` (a fixed-size accent bar whose opacity follows `useLinkStatus`, after 100 ms, pulse only without reduced motion, `aria-hidden`) on the tapped nav item, tab, row title or back link. A route-level skeleton comes back only for a page measured to wait well over ~300 ms on its data. |
| Errors | route-group `error.tsx` (`ErrorScreen`) + inline `Alert` for refused actions | errors say what happened and what to do; no apologies. |
| Success / "toasts" | inline `Alert tone="ok"` in a live region next to the action that caused it | no floating toasts (low bandwidth, screen readers, focus). |
| Confirmations | `ConfirmDialog` (native `<dialog>`, `--shadow-overlay`, `--scrim`) | only for destructive or irreversible actions (withdraw, decline, cancel plan, reject); names the action on its button ("Withdraw pitch", not "OK"); Escape and the second button cancel; focus returns to the trigger. |
| Tables | `DataTable` | `<table>` with a caption, inside a horizontally scrolling region with a visible label; numbers right-aligned. Used only where rows compare columns (billing invoices, milestones); everything else is a `RowList`. |
| Panels | `Panel` | the one bordered, `rounded-panel` box per screen (the assistant panel, the auth side panel). Cards are not a page structure. |

## Principles

1. **One vocabulary.** If "save" looks different on two screens, one is wrong. Every screen composes the components
   above; a class string repeated on two screens becomes a component or a token.
2. **Status is icon + words + tone**, the same `Badge` everywhere; at most two per row.
3. **The accent means "act here or you are here"**: primary buttons, the current nav item and tab, the whose-turn
   callout, focus. Never decoration.
4. **The one memorable thing stays where it is**: the bridge line on the landing page and the tracker stepper with its
   whose-turn callout. Everything else is quiet.
5. **Every screen has four states**: loading (the tapped link's pending hint; no route skeleton, see Loading), empty (one sentence, one action), error (what happened,
   what to do), success (inline confirmation). A screen without one of them is unfinished.

## Review against the brief (second pass)

- *Generic default check.* The palette is not cream + terracotta, not black + acid; no SaaS card grid (rows on paper,
  one panel per screen); no eyebrows, no numbered markers except the tracker stepper, which is a real sequence; no
  arrows appended to links. **Changed from the first draft:** the draft added an amber "caution" colour for held
  items and simulated numbers; dropped, because a fourth status colour adds noise and "simulated" is a fact to state
  in words (`Badge tone="neutral"` with the words "Simulated"), not a mood. The draft also used a card per Discover
  problem; dropped for `RowList`, since the problems compare better as rows.
- *Elevation.* Kept to one level, for things that float over the page; the page itself stays flat.
- *Motion.* No new motion. The bridge line drawing once stays the only authored moment; state changes (menu open,
  tab change) are instant or ≤150 ms colour transitions; reduced motion is respected globally.

## How to use (built in P16 part B)

Import from `frontend/components/ui/` (or `frontend/components/` for the navigation and route states). Compose these;
do not re-create their classes on a screen. Tokens are Tailwind utilities (`bg-accent-strong`, `hover:bg-wash-soft`,
`bg-error-wash`, `bg-ok-wash`, `border-error-line`, `border-ok-line`, `border-accent-line`, `backdrop:bg-scrim`,
`shadow-overlay`); never write their `color-mix` inline (`app/globals.test.ts` fails the build if one reappears).

| Component | Import | Use it for |
|---|---|---|
| `Button`, `ButtonLink` (variants `primary`, `secondary`, `danger`, `link`) | `@/components/ui/Button`, `@/components/ui/ButtonLink` | actions; `danger` for delete, withdraw, decline (outlined, never filled, never `data-primary`) |
| `PageHeader`, `BackLink` | `@/components/ui/PageHeader`, `@/components/ui/BackLink` | a page's back link, h1, one-sentence lead and the primary action's slot |
| `Section` | `@/components/ui/Section` | a titled part of a page: h2, optional description, optional secondary `link` |
| `RowList`, `Row` | `@/components/ui/RowList` | lists of things; `Row` takes `title`, `href` (stretched link), `meta`, `badges` (a tuple of at most two: `tsc` refuses a third), `figure` |
| `DescriptionList`, `Description` | `@/components/ui/DescriptionList` | label/value facts; `figures` for amounts and dates, `dense` inside a row |
| `Badge` | `@/components/ui/Badge` | a status: `tone` (`accent`, `ok`, `error`, `neutral`), `icon`, words; `solid` only for the one "Your turn"/"Needs you" marker; `data-chip`/`data-badge` pass through |
| `Callout` | `@/components/ui/Callout` | a static notice (no live role): `tone` (`info`, `ok`, `error`, `neutral`), optional `title`; replaces every coloured left rule |
| `Alert` | `@/components/ui/Alert` | a notice that appears because something happened (announced); same tones as `Callout` |
| `TabNav` | `@/components/ui/TabNav` | views of one page as link tabs (`label` required, `items`, `current`) |
| `PortalNav` (behind `DevNav`, `OrgNav`, `AdminNav`) | `@/components/PortalNav` | a portal's sections; use the three wrappers on screens |
| `EmptyState` (`EmptyStateFrame` for a button action in a client form step) | `@/components/ui/EmptyState`, `@/components/ui/EmptyStateFrame` | empty and closed states: one sentence, one action (`primary` when it is the screen's one action; `rule={false}` under a tab strip) |
| `LinkPending` | `@/components/ui/LinkPending` | inside a `next/link` whose destination may take a moment (already in `PortalNav`, `TabNav`, `Row` titles and `BackLink`); no `loading.tsx` |
| `NotFoundScreen` | `@/components/NotFoundScreen` | the one root `app/not-found.tsx`: static (no session read, no client component, plain links), since Next.js embeds it in every page's payload |
| `ConfirmDialog`, `openConfirm` | `@/components/ui/ConfirmDialog` | destructive or irreversible steps only; the confirm button names the action; open with `openConfirm(ref.current)` |
| `Panel` | `@/components/ui/Panel` | the one `rounded-panel` box of a screen (`variant="field"` or `"wash"`) |

`DataTable` is not built: no screen has a `<table>` yet (rows that compare columns: billing invoices, milestones);
add it with its first use.
