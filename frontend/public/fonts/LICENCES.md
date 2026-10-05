# Self-hosted fonts (Jacaranda, D-55, 2026-10-04)

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
