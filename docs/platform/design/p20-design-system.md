# P20 design system: Jacaranda

The owner's brief (2026-10-04, D-55): the P18 look changed too little; fonts, colour, the landing page and the section
layouts must change visibly, to the standard of a world-class product, without breaking a component or a flow. This
document replaces `p18-design-system.md` as the visual authority. Token names stay the same, so the code that reads
them does not change; their values, the type, the kit and the layouts do.

## Why P18 read as unchanged

The audit (screenshots in the session scratchpad, `p20/before/`) found the P18 world sits in the most common
generated-design cluster: a warm cream page, a high-contrast book serif for headings and one deep green. On top of
that the type was small (a 56 px hero, 21 px section titles), every section was the same thin-bordered white box on
cream, grids left orphans (three recommendations in a two-column grid), and nothing on any screen had weight. Changing
the green or the serif alone would not be seen. The redesign changes the world.

## The world

**Subject.** Wazo means "idea" in Swahili. Kenyan developers publish solutions to real local problems with timestamped
proof of what they submitted; organisations (telcos, SACCOs, counties, NGOs) find them, read them under NDA and agree
the next step on one tracker both sides see.

**Where it comes from.** Nairobi in October: the jacaranda avenues in full bloom, violet against the dusk, and the
kanga, East Africa's printed cloth, with its bold border (pindo) framing a centre (mji) and a message (jina). The
violet is the brand; saffron from the kanga's yellows is its warm second; the lattice band stays as the kanga border
and now frames things instead of decorating a header.

**Use scene.** Developers on mid-range Android phones in daylight, on the move and on Slow 4G; reviewers at desks.
Light is the default (bright ambient light), dark is a first-class second.

**Modes.** The landing and the public pages persuade: one bold place, the night hero. The portals operate: quiet,
precise, brand in the details (the violet, the saffron "your turn", the display face on titles and figures).

## Colour

Core palette (light):

| Name | Hex | Role |
|---|---|---|
| Bloom | `#5A3FC0` | The accent: primary buttons, links, the current step, focus. White on bloom 7.2:1; bloom on canvas 6.7:1 |
| Night | `#1E1640` | Deep jacaranda dusk: the landing hero and proof bands, the footer, the auth panel. Text on night `#EEEAF8` 14.3:1 |
| Saffron | `#F4B53F` | The warm second, from the kanga: "Your turn", the landing's call on night, the lattice's second tone. Never text on light; ink on saffron 9.5:1 |
| Petal | `#EFEBFC` | Bloom's wash: selected rows, the active nav item, info notices. Bloom on petal 6.2:1 |
| Ink | `#1B1730` | Text: 16.1:1 on canvas. A violet ink, not a grey near-black |
| Canvas | `#F7F6FB` | The page: a cool, faintly violet white (not cream). Cards are white (`#FFFFFF`) on it |

Supporting: ink-soft `#5E5873` (6.3:1), line `#E4E1EE`, ochre `#8A5800` (warm text on light, 5.6:1), leaf `#12784A`
(success, 5.1:1), error `#B3261E` (6.1:1), night-soft `#B9B0D9` (8.3:1 on night), night-line `#3A2F66`.

Dark: canvas `#100C1D`, field `#19142A`, ink `#EEEAF8` (16.3:1), ink-soft `#B5AECC` (8.4:1 on field), line `#2D2643`,
bloom `#A996FF` (7.8:1; canvas-coloured text on it 7.8:1), petal `#241C44`, saffron `#F6C155` (11.6:1), leaf `#6FD3A0`,
error `#FF8A80`, night bands `#1E1640` stay (lighter than the dark canvas, so a band still reads as a band).

Rules: status is always icon + words + colour; saffron fills carry ink text; no gradient text, no gradient washes as
decoration (the one glow behind the hero composition is a soft radial light, not a wash); shadows are tinted night,
with an offset and a blur.

## Type

| Face | Use | File |
|---|---|---|
| Bricolage Grotesque (OFL), weights 500–800, optical size pinned at 56, width 100 | Display: h1, h2, the hero, figures in stat tiles, the wordmark | `public/fonts/bricolage-grotesque-v1.woff2`, about 34 KB |
| Hanken Grotesk (OFL), weights 400–700 | Text and UI: body, labels, buttons, card titles, tables | `public/fonts/hanken-grotesk-v1.woff2`, about 20 KB |
| IBM Plex Mono (kept) | Data only: certificate IDs and fingerprints | unchanged |

Bricolage is a contemporary grotesque with hand-cut irregularities and ink traps; set big and tight it has the
confidence of Nairobi's printed signage without imitating it. Hanken is open and plain at 14–16 px on a cheap
screen. They are clearly two voices: the display face never sets running text; the text face never sets a page title.

Scale (rem on a 16 px base): 0.8125 (meta, chips) · 0.875 (secondary) · 1 (body) · 1.25 (lead) · 1.5 (section
title) · 2 (page title, phones) · 2.5 (page title from 1024 px) · 2.75 / 4.25 / 4 (the landing hero: phones / 1024 px, stacked / 1280 px, beside the composition). Display
tracking −0.02em at section size, −0.035em at hero size; line height 1.0–1.05 for the hero, 1.15 for titles, 1.6 for
body. Body measure ≤ 68 ch. Figures are tabular wherever they line up.

## Shape, depth and motion

- Radii: buttons and chips are pills (the round end reads as touchable at 360 px); inputs 10 px; cards and panels
  16 px; the hero composition's cards 18 px.
- Depth: cards are white on canvas with a hairline; only raised cards (the one that needs you, overlays, the hero
  composition) carry a shadow, tinted night with an offset (`0 12px 32px -16px`).
- Motion: one authored moment per page. On the landing, the hero composition's three cards settle in sequence and the
  tracker's current step lights once; reduced motion shows them in place. Controls answer in 180 ms with an
  exponential ease-out.
- Browser surfaces: selection petal on ink, caret bloom, focus 2 px bloom with a 2 px offset, scrollbars in line and
  ink-soft, tabular numerals in tables.

## Layout

### Landing (1440)

```
╔═ lattice band (bloom/saffron) ═══════════════════════════════════════════════════════════╗
  [W] Wazo        How it works   For organisations   Check a certificate        Log in
██ NIGHT ██████████████████████████████████████████████████████████████████████████████████
█  Local solutions                              ┌ tracker card (white) ──────────────┐    █
█  for the organisations                        │ Cold chain for dairy co-ops  ◉ turn │    █
█  that need them        (64 px, left, balanced) │ ●━━━●━━━○───○───○                   │    █
█                                               └─────────────────────────────────────┘   █
█  lead, 20 px, night-soft, ≤ 52 ch         ┌ scout match ┐        ┌ certificate + seal ┐  █
█  [Create an account]  Check a certificate └─────────────┘        └────────────────────┘  █
█  Already have an account? Log in                                                         █
██████████████████████████████████████████████████████████████████████████████████████████
═ lattice band ═
  One tracker, both sides     the five stages as one line across the page, each stage
                              with what each side does there (the product's spine)
  ┌ For developers (white, wide) ───────────┐ ┌ For organisations (petal) ─────────┐
  │ three points + the pitch it leads to    │ │ three points + a scout match       │
  └─────────────────────────────────────────┘ └────────────────────────────────────┘
  What you can do (asymmetric: 7 + 5 columns, then 5 + 7), each a miniature of the
  screen it names: Discover trends · Problem Briefs · Teaser checks · Notifications
██ NIGHT: proof ███ seal (large) │ three facts │ check a certificate [ ID ][Check] ███████
  Questions (h2 left, answers right, <details>, no script)
▓▓ BLOOM: closing ▓▓ one line + Create an account (a bloom panel between the night proof
   band and the night footer, so three night bands never meet) ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
██ footer (night) wordmark · product, developers, organisations, trust columns · theme ██
```

Phones (375): one column; the hero headline at 44 px over four balanced lines ("organisations" sets the
limit at 360 px); the composition shows the tracker card and the
certificate; the stage line becomes a vertical list; every grid becomes one column, in reading order.

### Portals (operate)

```
╔ lattice ═══════════════════════════════════════════════════════════════════════╗
 [W] Wazo  Prototype                                         (bell)  (avatar ▾)
 ┌ rail ─────────┐  Page title (Bricolage 40)                      [Primary]
 │ ▣ Home        │  one-line lead
 │ ◎ Discover    │  ┌ stat ┐┌ stat ┐┌ stat ┐┌ stat ┐   figures in Bricolage 36
 │ ▤ My ideas    │  Section title (Bricolage 24) ............. Section link
 │ ⇄ Engagements │  content on white cards, 16 px radius, hairline, grid auto-fill
 │ ▥ Companies   │  so a third card never sits alone under two
 └───────────────┘
```

Rules for every screen: the page title in the display face; section titles in the display face at 24 px with more
space above than below; cards only where a thing is a thing (a row of a list is a row, not a card); grids fill from
`auto-fill, minmax(18rem, 1fr)`; the one primary action is the bloom pill top right (full width at 360 px); the
active nav item is a petal pill with bloom text; "Your turn" is the only saffron on a portal screen.

## Checked against the generic defaults

Before building, the plan was compared with what any similar brief produces:

- Cream page + serif + one accent (the P18 world): replaced by a cool canvas, a grotesque display face and a
  two-colour palette grounded in the jacaranda and the kanga.
- Near-black page with one acid accent: avoided. The night is a deep violet used in bands, the page itself stays
  light, and the warm second is saffron, chosen from the kanga, not for shock.
- The SaaS card kit: the feature section uses five different working miniatures in an asymmetric grid, not identical
  icon-and-text cards; portal cards keep one radius but only raised cards carry a shadow.
- Template chrome: no eyebrow labels above headings, no all-caps labels, no "→" appended to links, no section numbers
  except the tracker's five stages, which are a real sequence.
- Gradient text and decorative glass: none.

## What stays

Every role, label, `data-*` hook and string key the tests and the product rely on; the one primary action per screen;
≤ 2 chips per card; 44 px targets; 360 px first; the 150 KB gzipped JS budget per route (styling moves into CSS
component classes, which also takes bytes out of the client bundles); English and Swahili parity; demo-honesty labels.
