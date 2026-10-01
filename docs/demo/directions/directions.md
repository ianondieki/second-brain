# Brand and visual directions (P18 step 1; owner decision D-52)

> **Decided 2026-10-01:** the owner chose the name **Wazo** and direction **C** with B's lattice as the single signature.
> Only direction C's screenshots (`c/`), mark and wordmark are kept here as the record; the rest was removed. The system
> as built is in `docs/platform/design/p18-design-system.md`.

The product works and is accessible but looks like a plain form. This page compares three complete visual directions
on the same real screens, proposes five product names, and recommends one of each. Nothing here is merged into a
product screen: everything renders in the development-only `/design-lab` route (`frontend/app/(lab)/design-lab`,
`*.lab.tsx` files that only `next dev` resolves; a production build has no trace of it, its fixtures or its fonts).

How to look: `cd frontend && npm run dev`, open `http://localhost:3000/design-lab`. Every screen × direction × light/dark
is linked there; `?bare=1` hides the switch bar. The screenshots in this folder (`a/`, `b/`, `c/`; `<screen>-<theme>-<width>.jpg`,
9 screens × 2 themes × 2 widths each) were taken by `frontend/scripts/design-lab-shots.mjs` on 2026-10-01.

## 1. Name candidates (no trademark search; obvious clashes flagged)

| Name | Say | Means | Notes |
|---|---|---|---|
| **Wazo** | WAH-zo | idea (Swahili) | Two syllables in both languages, four letters, `wazo.co.ke` style. The product is where ideas meet organisations. No big-brand look-alike known. **Recommended.** |
| **Hati** | HAH-tee | certificate, document, deed (*hati miliki* = title deed) | Names the proof-of-authorship story directly; four letters. No big-brand clash known. Second choice. |
| Kiungo | kee-OON-go | link, joint, connector | Says what the product does; three syllables, less snappy in English. |
| Buni | BOO-nee | to invent, to design (*kubuni*) | Short and apt. Flag: Buni Media is a known Nairobi animation studio. |
| Kuza | KOO-za | to grow, to nurture | Short, warm. Flag: "Kuza Biashara" is a Kenyan agribusiness programme. |

Left out for obvious clashes: **Daraja** (bridge; Safaricom's M-Pesa API), **Jenga** (the board game), **Tuko** (a
large Kenyan news site), **Soko** (several brands), **Ushahidi** (the Kenyan civic-tech organisation), **Pamoja**
(many organisations). The lab letters every wordmark "Wazo" as the placeholder until you choose; the three marks are
`logo-{a,b,c}.svg` and the wordmarks `wordmark-{a,b,c}.svg` (live text; step 2 converts the chosen one to paths).

## 2. The three directions

Each direction is a full token set (light and dark, AA contrast on paper and on field in both), a typeface pairing
(open licence, self-hosted latin-subset variable WOFF2, `font-display: swap`; licences in
`frontend/app/(lab)/design-lab/fonts/LICENCES.md`), radius, elevation, iconography, an empty-state illustration and a
motion style. The `tokens` screen of each direction shows all of it on one page.

| | A · Confident fintech | B · Warm Nairobi | C · Editorial trust |
|---|---|---|---|
| Idea | Money infrastructure: the certificate and tracker are instruments | Unmistakably from here: red soil, sand, a kanga-cut lattice | A registry: the certificate looks like something a lawyer files |
| Paper / ink (light) | `#F4F6FA` / `#0C1424` | `#F7F1E8` / `#2B1D15` | `#FBFAF6` / `#1A1916` |
| Accent | cobalt `#2140E8` (7.6:1 on paper) | murram `#B6401C` (6.4:1) | deep green `#1F5E49` (7.4:1) |
| Flourish (seal, lattice, art only) | `#7D93FF` | ochre `#C98C1E` | `#B8A46A` |
| Dark paper / accent | `#0B111E` / `#8DA0FF` | `#1B1512` / `#F2905F` | `#131412` / `#7FCBAB` |
| Display / text / figures | Manrope 700 / Manrope / JetBrains Mono | Bricolage Grotesque 600 / DM Sans / JetBrains Mono | Newsreader 500 / IBM Plex Sans / IBM Plex Mono |
| Type scale | 1.25 on 16 px, tracking −0.022em | 1.25, tracking −0.015em | 1.333 (titles 28/36/48 px), tracking −0.01em |
| Radius (control / panel) | 8 / 14 px | 12 / 20 px | 6 / 12 px |
| Elevation | 1 px contact + cool ambient shadow; cards a hair above the paper | warm-tinted, slightly longer shadows; the primary button and whose-turn card float | hairlines; one wide, very soft shadow under the certificate sheet; overlays only |
| Icons | 1.75 px, square-ish, rounded caps | rounder 2 px strokes, soft corners | 1.5 px hairline feel, circular |
| Illustration | isometric line drawings on a faint grid | flat warm shapes with lattice fills | engraving-style thin lines, one green stroke |
| Motion | 140–200 ms ease-out, no overshoot | 180–240 ms with a slight overshoot on presses | 180–260 ms fades with a 4 px rise |
| Signature element | the top bar and tab bar as a white strip over cool paper; the cobalt primary with its coloured shadow | a 6 px two-tone lattice band on the top bar, every wash panel, the certificate and the email header | the serif at optical size 48 on every title; the seal mark |
| Logo mark | two nodes joined by one bar (a circuit) | a kanga diamond cut by a span | a seal ring with one tick |

What stays identical across the three: every component, layout, string, state and behaviour; one primary action per
screen; 360 px first; WCAG 2.2 AA; the demo labels ("Seeded example", "(fixture)", "Sample prices, not final") as
small neutral badges.

## 3. What the screenshots show

- **Landing** (`landing-*`): the real hero (title, lead, "Create an account", the drawn bridge line) plus the live
  product visual the brief asks for: the real tracker stepper on a seeded engagement in a floating card.
- **Developer Home** (`home-*`): Needs you, Recommended for you with Why chips, the others, latest ideas, security.
- **Certificate** (`certificate-*`): the idea page's real Certificate section, then a preview of the step-3 showpiece
  sheet (seal, timestamp, fingerprint, QR to `/verify`).
- **Tracker** (`tracker-*`): the real `EngagementScreen` at "Mutual NDA", both parties owing a signature, the
  developer's turn, the "Sign the mutual NDA" primary action.
- **NDA + full proposal** (`proposal-*`): the organisation's proposal page at the Evaluation NDA step (fixture text).
- **M-Pesa checkout** (`checkout-*` and `checkout-success-*`): the real simulated checkout, confirm step and the
  success state.
- **Email** (`email-*`): the EM7 daily reminder as a branded, responsive HTML email in each direction (table layout,
  inline hex values, 600 px), a preview of the step-3 template.
- **Tokens** (`tokens-*`): the direction's whole system on one page.

## 4. Recommendation

**C, Editorial trust, as the base, with B's lattice as its one East African signature** (a single muted band in
C's flourish colour on the top bar, the certificate sheet and the email header, and the kanga diamond as the seal's
inner shape). Name: **Wazo**.

Why C: the product's trust artefact is the certificate, and the enterprise side signs an NDA before it sees anything.
A registry voice (a serif at display size, generous whitespace, one quiet green) makes those moments look like what
they are, and it is the direction that reads *calm* at 375 px, where the other two rely on colour to carry
hierarchy. It is also the only direction that does not resemble the category: cobalt on cool paper (A) is the
benchmark fintechs' own default and would make the product look like one more of them; B is distinctive, but its murram carries every link and every "current" chip, so list-heavy screens (Home, the
tracker) read warmer and busier than C, as the `home-*` and `tracker-*` shots show; it would need a second, quieter
link colour to stay calm on the staff console.

Why add B's lattice: C alone is placeless. The band is six pixels, two tones, and appears in three places; it gives
the East African signature the brief asks for without a pattern anywhere near text.

If you would rather have the startup energy of A: take A's palette and keep C's type (Newsreader headings over
Manrope). Those two mix well; A with B's band does not (cobalt against ochre and murram clashes).

Open points for step 2, once you choose: convert the chosen wordmark to paths; decide whether the serif also sets
row titles (`h3`) or only page and section titles; the dark-mode toggle's place in the account menu; and the
Swahili wordmark variants if names differ by language (they do not for the five above).

## 5. Craft notes and known limits of the lab

- The lab previews directions through token overrides and a small scoped stylesheet (`lab.css`); step 2 renames the
  tokens (`--jacaranda` becomes `--accent`) and builds the real components (sheets, tiles, timeline, toasts).
- The fonts are Google Fonts' latin subsets (24–132 KB each); Newsreader carries an optical-size axis, hence its size.
- Email and the certificate sheet are lab compositions, not yet the product's components; the other six screens are
  the product's own components on fixture data.
- Dark mode is `?theme=dark` on the lab wrapper; the product's own toggle and `prefers-color-scheme` come in step 3.
