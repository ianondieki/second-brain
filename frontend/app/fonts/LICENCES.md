# Self-hosted fonts (direction C, chosen 2026-10-01; D-52)

All three are under the SIL Open Font License 1.1 (`OFL.txt`), fetched from Google Fonts' latin subsets on 2026-10-01
as variable WOFF2 files, loaded by `app/layout.tsx` through `next/font/local` with `font-display: swap` and a
size-adjusted fallback. The OFL permits bundling and self-hosting; it forbids selling the fonts alone and renaming
them under their reserved font names (the files keep their family names).

| File | Family (role) | Copyright / reserved font name | Upstream |
|---|---|---|---|
| `newsreader-latin.woff2` | Newsreader, instanced with fontTools to wght 500 and opsz 18–72 (display: page and section titles, the wordmark; 42 KB, from the 132 KB opsz 6–72 / wght 200–800 file) | © 2020 The Newsreader Project Authors (Production Type); RFN "Newsreader" | https://github.com/productiontype/Newsreader |
| `ibm-plex-sans-latin.woff2` | IBM Plex Sans, wght 100–700 (text) | © 2017 IBM Corp.; RFN "Plex" | https://github.com/IBM/plex |
| `ibm-plex-mono-latin.woff2` | IBM Plex Mono, wght 400 (fingerprints, codes) | © 2017 IBM Corp.; RFN "Plex" | https://github.com/IBM/plex |
