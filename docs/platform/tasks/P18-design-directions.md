# P18 step 1 — brand candidates and three visual directions (D-52; REQ-UX-01..04)

Owner brief of 2026-10-01 (recorded as D-52). Step 1 only: no product screen changes its look; the owner chooses a
name and a direction (or a mix) before step 2.

## Delivered

- `frontend/app/(lab)/design-lab/`: development-only route (`*.lab.tsx`, `pageExtensions` in `next.config.ts`; the
  production extension list is asserted by `next.config.test.ts`). Index with the five names and the wordmarks;
  `/design-lab/<a|b|c>/<screen>?theme=dark&bare=1` for nine screens on the product's own components with fixture data.
- Directions as token sets (`directions.ts`, light + dark), scoped rules (`lab.css`), fonts (`fonts/`, OFL, licences
  recorded), marks (`brand/Logo.tsx`), fixtures (`fixtures.ts`), screens (`screens/`).
- `frontend/scripts/design-lab-shots.mjs`: the 108 screenshots in `docs/demo/directions/`.
- `docs/demo/directions/directions.md`: the comparison and the recommendation; `logo-*.svg`, `wordmark-*.svg`.
- Product code: `app/(app)/dev/ideas/[id]/Certificate.tsx` (moved out of `page.tsx`, unchanged).

## Checks run

`npm run typecheck`, `npx eslint .`, `npx vitest run` (frontend), the lab smoke (every route 200 under `next dev`).

## Follow-ups (step 2, after the owner's choice)

- Delete the unchosen fonts and directions; convert the chosen wordmark to paths.
- Rename `--jacaranda` → `--accent` (and the Tailwind colour names) across components; add `--flourish`,
  `--shadow-card`, `--font-display`, motion tokens to `globals.css` with the dark-mode set.
- The certificate sheet and the branded email become product components and a Jinja template (`em7.html.j2`).

## Step 2 (2026-10-01): the design system and the four showpiece screens

Owner's choice: name **Wazo**; direction C with B's lattice as the one signature; C's dark mode. Delivered on the same
branch (`docs/platform/design/p18-design-system.md` is the system's record):

- Tokens, dark mode (system + remembered choice, applied before paint), self-hosted fonts in `app/fonts/`, motion,
  print rules; `--jacaranda` renamed `--accent` across the frontend.
- Brand: `components/brand/` (mark, wordmark, seal); the top bar shows the wordmark and a "Prototype" badge; every
  product string that named "Bridge" now says "Wazo" (frontend; the backend's `product_name` default and the EM7
  subject are for the emails round).
- New components: Lattice, Avatar, StatTile, Sparkline, ProgressBar, Card/CardGrid, Illustration (in every empty
  state), ThemeToggle, NeedsYouCard, EngagementCard, IdeaCard, CertificateSheet, PrintButton, HeroComposition.
- Screens: landing (new layout), Developer Home (`HomeContent`), the tracker, the certificate sheet.
- The lab (`/design-lab/<screen>`) now previews the product's own screens on fixtures for the chosen direction only;
  the unchosen fonts, directions and their screenshots were deleted (`docs/demo/directions/c/` stays as the record).
- Screenshots: `docs/demo/screenshots/p18/` (landing, home, tracker, certificate × light/dark × 375/1440, plus the
  proposal and checkout screens untouched for comparison).
- Tests added: `lib/theme.test.ts`, `components/ThemeToggle.test.tsx`, `components/ui/Avatar.test.tsx`,
  `components/ui/StatTile.test.tsx` (tile, sparkline, progress bar), `homeStats` in `app/(app)/dev/home.test.ts`;
  updated: `globals.test.ts` (two shadows, dark-mode parity), the top bar tests, `next.config.test.ts`.
- Checks: `npm run typecheck`, `npx eslint .`, `npx vitest run` (1274 tests), `next build` (production build, the
  lab answers 404). Not run here: the Playwright e2e suite (needs the compose stack); the selectors it uses on Home
  and the tracker were kept (`[data-primary]`, `[data-home='others'] article [data-chip]`, `[data-whose-turn]`, the
  "Stages" list, `[data-actions]`).

Waiting on the owner's review of the four screens before the roll-out to the remaining screens.
