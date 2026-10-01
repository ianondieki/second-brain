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
| `--flourish` | `#B89A4A` | `#A08B48` | the lattice's second tone, seals, art; never text or status |
| `--ok` / `--error` | `#1F6B47` / `#9E2A1F` | `#7AC79A` / `#FF8F7E` | status, always with an icon and words |
| `--shadow-card` | `0 1px 0 … / 0.04, 0 16px 40px -24px … / 0.22` | from black | cards, sheets, tiles |
| `--shadow-overlay` | as before, re-tinted | from black | menus, dialogs, sheets over the page |

The derived mixes (`--accent-strong`, `--wash-soft`, the notice washes and lines, `--scrim`) keep their formulas
(`app/globals.test.ts`). Dark mode is its own set of steps, declared twice: on `html[data-theme="dark"]` (a choice)
and under `prefers-color-scheme: dark` when no choice was made (`lib/theme.ts`, `components/ThemeToggle.tsx`; the
choice is applied before paint by an inline script in `app/layout.tsx`). `viewport.themeColor` carries both.

**Type.** Newsreader (display: `h1`, `h2`, the wordmark, card titles that are the page's point), IBM Plex Sans
(text, `h3`), IBM Plex Mono (fingerprints, codes); OFL, self-hosted latin-subset variable WOFF2 through
`next/font/local` with `font-display: swap` (`app/fonts/LICENCES.md`). Scale 1.333 on 16 px: 14 / 16 / 21 / 28 / 36
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

The top bar (`TopBarBase`) shows the wordmark as the home link (accessible name "Wazo") and the muted "Prototype"
badge once per screen. Demo honesty labels stay neutral badges ("Seeded example", "(fixture)", "Illustrative
example", "Sample prices, not final").

## The four showpiece screens (this step)

- **Landing** (`app/(public)/page.tsx` → `LandingContent`): hero with the promise and the layered visual (the real
  stepper and progress bar, a scout match card, the certificate card), "How it works" in three numbered steps with
  icons (a real sequence), "Who it is for" as two cards, "Proof of authorship, not a promise" with the seal and three
  points (no protection claims; `locales.test.ts` keeps the approved logging phrasing), the final call to action on
  the wash with the lattice, and a footer with the appearance toggle.
- **Developer Home** (`app/(app)/dev/HomeContent.tsx`): four stat tiles (ideas with drafts, engagements with active,
  needs you, next deadline with days left), "Needs you" as `NeedsYouCard`s with the other party's avatar, the stage,
  "Your turn", the deadline and "Open the tracker", "Recommended for you" as cards, the other engagements and ideas as
  compact cards, the two-step sign-in line.
- **Tracker** (`components/tracker/EngagementScreen.tsx`): the whose-turn card now shows both parties' avatars with
  the awaited ones ringed; a segmented progress bar with "Stage n of 5: group"; the timeline (the `Stepper`, whose
  names never break inside a word) with the acting party's avatar on the current step on phones; the actions in a
  card headed "Now: stage". Every test selector (`[data-whose-turn]`, the "Stages" list, `[data-actions]`) is unchanged.
- **Certificate** (`app/(app)/dev/ideas/[id]/Certificate.tsx`): the sheet is the section's default view, placed right
  under the idea's actions; the links (public record, PDF when timestamped) and "Print or save as PDF" follow.

## Screens still on the old layout (next rounds, in demo-story order)

Sign-in and two-step, the first-login tour, My ideas list and the editor, `/verify`, Org Inbox (stat tiles with
sparklines where data exists), the NDA step and full-proposal view, scout matches and Discover, Plan & billing and
the checkout sheet, the staff console, the emails (`backend/.../em7.html.j2` and the auth mails; the backend's
`product_name` default still says "Bridge (working name)"), haptics, the CLOSED celebration, bottom-sheet dialogs.
