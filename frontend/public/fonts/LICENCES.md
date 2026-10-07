# Self-hosted fonts (Jacaranda, D-55, 2026-10-04; Fraunces added in P24, D-66, 2026-10-07)

All three are under the SIL Open Font License 1.1 (`OFL.txt`), fetched as Google Fonts' latin subsets (variable WOFF2)
on 2026-10-04 (the mono face on 2026-10-01), declared in `app/globals.css` (`@font-face`, `font-display: swap`, a
size-adjusted local fallback each) and preloaded from `app/layout.tsx` (the display and text faces; the mono face is
not). The files are served immutable for a year (`security-headers.ts`), so a changed file takes a new `-vN` suffix
(and the references above follow). The OFL permits bundling and self-hosting; it forbids selling the fonts alone and
renaming them under their reserved font names (the files keep their family names).

| File | Family (role) | Copyright / reserved font name | Upstream |
|---|---|---|---|
| `bricolage-grotesque-v1.woff2` | Bricolage Grotesque, instanced with fontTools to width 100, optical size 56 and weights 500–800, subset to Latin-1 plus typographic punctuation (display: page and section titles, the hero, figures, the wordmark; 34 KB, from the 132 KB opsz 12–96 / wdth 75–100 / wght 200–800 file) | © 2022 The Bricolage Grotesque Project Authors (Mathieu Triay); no reserved font name | https://github.com/ateliertriay/bricolage |
| `hanken-grotesk-v1.woff2` | Hanken Grotesk, instanced with fontTools to weights 400–700 (text and UI; 20 KB, from the 35 KB wght 100–900 file) | © 2021 The Hanken Grotesk Project Authors (Alfredo Marco Pradil); no reserved font name | https://github.com/marcologous/hanken-grotesk |
| `ibm-plex-mono-latin-v1.woff2` | IBM Plex Mono, wght 400 (fingerprints, codes) | © 2017 IBM Corp.; RFN "Plex" | https://github.com/IBM/plex |
| `fraunces-v1.woff2` | Fraunces upright, from the variable TrueType in the official Google Fonts repository (`google/fonts`, `ofl/fraunces/Fraunces[SOFT,WONK,opsz,wght].ttf`, fetched 2026-10-07), instanced with fontTools to SOFT 0, WONK 0, opsz 24–144 and wght 400–700, subset to Basic Latin, the Latin-1 letters and typographic punctuation (display: page and section titles; 46 KB, from 360 KB) | © 2018 The Fraunces Project Authors (Undercase Type, Phaedra Charles, Flavia Zimbardi); no reserved font name | https://github.com/undercasetype/Fraunces |
| `fraunces-italic-v1.woff2` | Fraunces italic, the same source (`Fraunces-Italic[SOFT,WONK,opsz,wght].ttf`), instanced the same way, subset to Basic Latin and punctuation (the landing hero's accent phrase only; 47 KB, from 415 KB) | as above | as above |
| `og/fraunces-og-v1.ttf`, `og/bricolage-og-v1.ttf` | Static TrueType instances for the share cards (`app/og`; next/og reads TrueType, not WOFF2): Fraunces at opsz 72, wght 560 (Latin) and Bricolage Grotesque at wght 760 (Basic Latin). Not served to pages | as above, and as Bricolage Grotesque | as above |
