# Self-hosted fonts (Jacaranda, D-55, 2026-10-04; Fraunces added in P24, D-66, 2026-10-07)

All three are under the SIL Open Font License 1.1 (`OFL.txt`), fetched as Google Fonts' latin subsets (variable WOFF2)
on 2026-10-04 (the mono face on 2026-10-01), declared in `app/globals.css` (`@font-face`, `font-display: swap`, a
size-adjusted local fallback each) and preloaded from `app/layout.tsx` (the display and text faces; the mono face is
not). The files are served immutable for a year (`security-headers.ts`), so a changed file takes a new `-vN` suffix
(and the references above follow). The OFL permits bundling and self-hosting; it forbids selling the fonts alone and
renaming them under their reserved font names (the files keep their family names).

| File | Family (role) | Copyright / reserved font name | Upstream |
|---|---|---|---|
| `bricolage-grotesque-v2.woff2` | Bricolage Grotesque, instanced with fontTools to width 100, optical size 56 and weights 600–800, subset to Basic Latin plus typographic punctuation (P24: the wordmark and the figures only; 21 KB, from the 132 KB opsz 12–96 / wdth 75–100 / wght 200–800 file; v1 was Latin-1, 34 KB) | © 2022 The Bricolage Grotesque Project Authors (Mathieu Triay); no reserved font name | https://github.com/ateliertriay/bricolage |
| `hanken-grotesk-v1.woff2` | Hanken Grotesk, instanced with fontTools to weights 400–700 (text and UI; 20 KB, from the 35 KB wght 100–900 file) | © 2021 The Hanken Grotesk Project Authors (Alfredo Marco Pradil); no reserved font name | https://github.com/marcologous/hanken-grotesk |
| `ibm-plex-mono-latin-v1.woff2` | IBM Plex Mono, wght 400 (fingerprints, codes) | © 2017 IBM Corp.; RFN "Plex" | https://github.com/IBM/plex |
| `fraunces-v1.woff2` | Fraunces upright, from the variable TrueType in the official Google Fonts repository (`google/fonts`, `ofl/fraunces/Fraunces[SOFT,WONK,opsz,wght].ttf`, fetched 2026-10-07), instanced with fontTools to SOFT 0, WONK 0, opsz 24–72 and wght 500–700 (what the pages set), subset to Basic Latin and typographic punctuation with kerning, ligatures and contextual forms (display: page and section titles; 37 KB, from 360 KB) | © 2018 The Fraunces Project Authors (Undercase Type, Phaedra Charles, Flavia Zimbardi); no reserved font name | https://github.com/undercasetype/Fraunces |
| `fraunces-ext-v1.woff2` | Fraunces upright, the same instance, subset to Latin-1 Supplement and Latin Extended-A (U+00A0–017F: names such as Wanjirũ and Zoé); declared with that unicode-range, so only a page that sets one of those letters in a title fetches it (43 KB) | as above | as above |
| `fraunces-italic-v1.woff2` | Fraunces italic, the same source (`Fraunces-Italic[SOFT,WONK,opsz,wght].ttf`), instanced to opsz 40–72 at wght 500, subset to the lower-case letters and punctuation (the landing hero's accent phrase only; 9 KB, from 415 KB) | as above | as above |
| `og/fraunces-og-v1.ttf`, `og/bricolage-og-v1.ttf` | Static TrueType instances for the share cards (`app/og`; next/og reads TrueType, not WOFF2): Fraunces at opsz 72, wght 560 (Latin) and Bricolage Grotesque at wght 760 (Basic Latin). Not served to pages | as above, and as Bricolage Grotesque | as above |
