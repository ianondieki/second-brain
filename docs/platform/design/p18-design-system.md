# P18 design system — Wazo (D-52; REQ-UX-01..04)

Written by the orchestrator with the `frontend-design` and `impeccable` skills in redesign mode after the owner chose
the name **Wazo** and direction C ("Editorial trust") with B's kanga-cut lattice as the single East African signature
(2026-10-01; `docs/demo/directions/directions.md`). It replaces the visual-style parts of `p16-design-system.md`
(which stays the record of the component vocabulary and the one-pattern-each rule). Precedence: `CLAUDE.md`, the
owner's brief (D-52), then `docs/spec/07` and `docs/spec/04` §4.6 for everything the brief did not replace
(accessibility, budgets, one primary action, 360 px first, no clutter), then this file, then any skill.

## Tokens (`frontend/app/globals.css`)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--paper` | `#FBFAF6` | `#131412` | page |
| `--field` | `#FFFFFF` | `#1B1C19` | inputs, cards, sheets |
| `--ink` / `--ink-soft` | `#1A1916` / `#5C5A53` | `#ECE9E1` / `#B4B0A5` | text (16.4:1, 6.6:1 on paper) |
| `--line` | `#DEDACF` | `#30312C` | hairlines |
| `--accent` / `--accent-wash` | `#1F5E49` / `#E5EFE9` | `#7FCBAB` / `#1F2F28` | act here, current, focus; selected, info |
| `--flourish` | `#B89A4A` | `#A08B48` | the lattice's second tone and illustration; never text |
| `--warm` / `--warm-wash` | `#7A5A12` / `#F6EFDC` | `#E0B85A` / `#2A2416` | the warm secondary accent from the lattice's ochre (6.1:1 light, 9.9:1 dark), used sparingly: the solid "Your turn" badge, success notices (`Alert`/`Callout` tone `ok`), the seal's inner ring and the mark's inner ring |
| `--ok` / `--error` | `#1F6B47` / `#9E2A1F` | `#7AC79A` / `#FF8F7E` | status, always with an icon and words |
| `--shadow-card` | `0 1px 0 … / 0.04, 0 16px 40px -24px … / 0.22` | from black | cards, sheets, tiles |
| `--shadow-overlay` | as before, re-tinted | from black | menus, dialogs, sheets over the page |

The derived mixes (`--accent-strong`, `--wash-soft`, the notice washes and lines, `--scrim`) keep their formulas
(`app/globals.test.ts`). Dark mode is its own set of steps, declared twice: on `html[data-theme="dark"]` (a choice)
and under `prefers-color-scheme: dark` when no choice was made (`lib/theme.ts`, `components/ThemeToggle.tsx`; the
choice is applied before paint by an inline script in `app/layout.tsx`). `viewport.themeColor` carries both.

**Type.** Newsreader (display: `h1`, `h2`, the wordmark, card titles that are the page's point), IBM Plex Sans
(text, `h3`), IBM Plex Mono (fingerprints, codes); OFL, self-hosted latin-subset variable WOFF2 declared in
`app/globals.css` (`@font-face`, `font-display: swap`, size-adjusted local fallbacks) and preloaded from `app/layout.tsx`
(`public/fonts/LICENCES.md`). Scale 1.333 on 16 px: 14 / 16 / 21 / 28 / 36
/ 48; the landing title 56 px. **Radius** 6 px controls, 12 px cards and sheets. **Motion** `--motion-fast` 180 ms,
`--motion-base` 260 ms, `--ease-out` cubic-bezier(0.16, 1, 0.3, 1): every control transitions on hover and presses
sink 1 px; the seal's ring draws once; reduced motion turns all of it off. **Print**: the certificate sheet prints
alone (`data-print-sheet`); chrome and buttons hide.

**The lattice** (`components/ui/Lattice.tsx`, utility `lattice-band`): a 6 px two-tone band of triangles (accent and
flourish) on the top bar, the landing hero's frame and final call to action, and the certificate sheet. Decorative,
never behind text, never as wallpaper.

## Components added (`frontend/components/`)

| Component | Use |
|---|---|
| `brand/Logo` (`LogoMark`, `Wordmark`), `brand/Seal` | the mark, the wordmark in every top bar, sheet and email; the seal on the certificate and the landing proof section |
| `ui/Lattice` | the band |
| `ui/Avatar` | initials; round for a person, a rounded square for an organisation; a ring for the party whose turn it is |
| `ui/StatTile` + `ui/Sparkline` | the figures at the top of Home and the org Inbox; a sparkline only when a series exists (none yet on Home) |
| `ui/ProgressBar` | segmented for the tracker's five groups; `role=progressbar` |
| `ui/Card`, `ui/CardGrid` | raised (card shadow), flat (compact lists), wash; `RowList cards` turns an existing row list into compact cards |
| `ui/Illustration` | engraving-style line drawings for empty and quiet states; `EmptyStateFrame` shows one by default |
| `tracker/NeedsYouCard`, `tracker/EngagementCard`, `dev/ideas/IdeaCard` | Home's prominent and compact cards |
| `certificate/CertificateSheet`, `certificate/PrintButton` | the showpiece sheet with seal, lattice edge, QR to `/verify`; printable |
| `landing/LandingContent`, `landing/HeroComposition` | the landing page and its layered product visual (illustrative, labelled) |
| `ThemeToggle` | system / light / dark, in the account menu and the landing footer |

**Cards that are links.** A card holds one link, its title, stretched over the whole card (`cardLinkClass`, `Card
interactive`): no underline on the title, the accessible name is the title, the card shows the hover (accent-line
border, overlay shadow) and the focus ring; the link's own outline is off. "Open the tracker" on a Needs-you card is
the link's visual cue, not a second link. Underlines stay for links inside running text. Rows turned into cards
(`RowList cards`) keep their title link but drop the underline. Cards in a grid are equal height. Avatars are round
for people and organisations alike.

**Stat tiles** say what they count: Ideas "2 published · 1 draft" (a published idea's saved edits are "unpublished
changes" on its own card, not a draft); the deadline tile shows "Oct 3" with "in 2 business days", "Due today" or
"Overdue" under it, never wrapping at 375 px.

**The certificate's verify address** comes from `NEXT_PUBLIC_SITE_ORIGIN` (frontend/.env.example) plus the path; with
no origin configured the sheet and its QR carry the path alone, never the server's own host.

The top bar (`TopBarBase`) shows the wordmark as the home link (accessible name "Wazo") and the muted "Prototype"
badge once per screen. Demo honesty labels stay neutral badges ("Seeded example", "(fixture)", "Illustrative
example", "Sample prices, not final").

## The four showpiece screens (this step)

- **Landing** (`app/(public)/page.tsx` → `LandingContent`): an eight-word headline on two lines with the long
  sentence as the subhead, then the product visual as the hero: a browser frame over a soft backdrop holding the real
  tracker card (avatars, "Your turn", the stepper), a scout match card and the certificate card with a little depth,
  every word at least 13 px, "How it works" in three numbered steps with
  icons (a real sequence), "Who it is for" as two cards, "Proof of authorship, not a promise" with the seal and three
  points (no protection claims; `locales.test.ts` keeps the approved logging phrasing), the final call to action on
  the wash with the lattice, and a footer with the appearance toggle.
- **Developer Home** (`app/(app)/dev/HomeContent.tsx`): four stat tiles (ideas with published and drafts,
  engagements with active, needs you, next deadline), "Needs you" as `NeedsYouCard`s with the other party's avatar,
  the stage, "Your turn", the deadline and the way in, "Recommended for you" as cards (a seeded example carries the
  small "Demo data" badge, its full sentence on press), the other engagements and ideas as compact cards; two-step
  sign-in appears only as a notice while it is off.
- **Tracker** (`components/tracker/EngagementScreen.tsx`): the whose-turn card shows both parties' avatars with
  the awaited ones ringed and says the next step once (one sentence when both owe the same step); the timeline (the
  `Stepper`, whose names never break inside a word) is the one progress indicator, with "Now: stage" on the current
  step and, on phones, the acting party's avatars and "Since <date>"; the actions in a card. Every test selector
  (`[data-whose-turn]`, the "Stages" list, `[data-actions]`) is unchanged.
- **Certificate** (`app/(app)/dev/ideas/[id]/Certificate.tsx`): the sheet is the section's default view, placed right
  under the idea's actions; the links (public record, PDF when timestamped) and "Print or save as PDF" follow.

## Screens still on the old layout (next rounds, in demo-story order)

Sign-in and two-step, the first-login tour, My ideas list and the editor, `/verify`, Org Inbox (stat tiles with
sparklines where data exists), the NDA step and full-proposal view, scout matches and Discover, Plan & billing and
the checkout sheet, the staff console, the emails (`backend/.../em7.html.j2` and the auth mails; the backend's
`product_name` default still says "Bridge (working name)"), haptics, the CLOSED celebration, bottom-sheet dialogs.
