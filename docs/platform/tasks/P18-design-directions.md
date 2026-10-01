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
