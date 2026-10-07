# Licensed Kenyan photographs for the landing and Explore (P24-A, D-66)

Read on 2026-10-07 from Wikimedia Commons through its public MediaWiki API (read-only: no account, no credentials, no authenticated endpoint; TLS verification never disabled; `User-Agent: WazoDesignResearch/1.0 (ondiekiian0@gmail.com)`). This note records what was chosen and why; the files are in `frontend/public/photos/` with `CREDITS.md` and `index.json`.

## Question

Which ten licensed (CC0, CC BY, CC BY-SA) landscape photographs of Kenyan places and everyday economic life can the P24 landing county strip and the public Explore page use, with title, author, licence, source URL and the exact attribution line, vendored as AVIF and WebP (never hot-linked) (D-66, REQ-UX-03 onboarding county context and the public pages; spec 04 principle 4: no third-party logos, nothing that reads as an endorsement)?

## Short answer

Ten photographs, found and converted: Nairobi x3 (CBD skyline, golden-hour aerial, jacaranda carpet), Mombasa x2 (Old Town waterfront, Likoni ferry), Kisumu (Lake Victoria shore), Nakuru (Lake Nakuru), Eldoret (a town street), Ongata Rongai (a produce market, CC0) and a Kenyan tea farm (CC0). Licences: CC BY-SA 4.0 x5, CC BY-SA 2.0 x1, CC BY-SA 3.0 x1, CC BY 2.0 x1, CC0 x2. Each carries a clear `LicenseShortName` and `LicenseUrl` in Commons `extmetadata` and is >= 1920 px wide at source. Every 1600 px file is 113,959 B to 154,890 B (limit 160 KB) and every 800 px file is 51,901 B to 67,778 B (limit 70 KB); all five files per slug exist. Not found: a Nairobi jacaranda-lined avenue (only a ground-level blossom carpet and a hotel photograph), a telecom-tower photograph with a documented Kenyan location (the one candidate has an advertorial description and no place), a workshop photograph without clearly visible faces, and a bright, attractive Eldoret photograph without prominent advertising (the chosen one is overcast and rainy). The tea photograph names no county on Commons, so its county is given as "Kenya".

## Method

1. `action=query&list=search` / `generator=search` with `srnamespace=6` (File namespace) and `filetype:bitmap`, one query per place or theme (list below), keeping only files whose `extmetadata.LicenseShortName` starts with CC0, CC BY or CC BY-SA, width >= 1600 px and width >= 1.2 x height.
2. For each shortlisted file: `prop=imageinfo|categories`, `iiprop=url|extmetadata|size`, `iiurlwidth=1920`; the 1920 px Commons thumbnail was downloaded to a scratch directory outside the repository (never the repository). Contact sheets were viewed by eye; rejected for visible brand as subject (a Coca-Cola kiosk in a boda-boda photograph, an Airtel shop front in a Mombasa tuk-tuk photograph), a camera date stamp, GFDL-only or unclear location, or poor light.
3. Conversion with Python Pillow 12.3.0 built-in AVIF and WebP encoders (`PIL.features.check('avif')` true; `cwebp` and `avifenc` not installed; `pillow-avif-plugin` not installed and not needed; no new dependency committed). Bisection on quality for each file: target <= 120,000 B at 1600 px and <= 55,000 B at 800 px, relaxed to 155,000 B / 68,000 B where the target would need AVIF quality below 45 or WebP below 50. EXIF and ICC profiles removed (converted to sRGB first); `<slug>-blur.jpg` is 24 px wide, JPEG, 383 to 440 B. The very detailed `kisumu-lake-victoria` and `kenya-tea` 1600 px WebP files needed a 0.5 px Gaussian softening to fit the limit (WebP is the fallback format; AVIF is not softened). The D-66 card asks for under 120 KB each; several 1600 px files are between 120 KB and 155 KB (see the bytes table) because the brief's limit is 160 KB.

## Search queries (all 2026-10-07)

`Nairobi skyline`; `Nairobi city skyline CBD`; `Nairobi central business district`; `Nairobi jacaranda`; `Nairobi jacaranda trees street`; `Jacaranda Nairobi avenue`; `Mombasa Old Town`; `Mombasa harbour`; `Kisumu Lake Victoria`; `Kisumu`; `Nakuru`; `Nakuru town`; `Lake Nakuru landscape flamingos`; `Menengai crater`; `View over Nakuru`; `Kenya Rift Valley landscape Nakuru`; `Eldoret`; `Eldoret town`; `Eldoret Kenya street`; `Eldoret Uasin Gishu County`; `Moi University Eldoret`; `Eldoret skyline`; `Eldoret wheat maize field`; `Uasin Gishu farm`; `Kenya market produce`; `Wakulima market Nairobi`; `Gikomba market`; `Kenya vegetable market stall`; `Kenya tea plantation`; `Kenya tea Kericho`; `Kenya dairy farm`; `Kenya dairy cows farm landscape`; `Safaricom mast Kenya`; `Kenya telecommunications tower`; `Kenya cell tower`; `Kenya workshop welding`; `Kenya welder workshop`; `Kenya mechanic garage`; `Kenya carpenter workshop`; `Jua Kali Nairobi`; `Nairobi matatu stage`; `boda boda Kenya`. The API returned empty responses for several queries on the first attempt (for example `Nairobi skyline`, `Kisumu Lake Victoria`, `Kenya cell tower`); retrying after a pause or varying the query worked, as the brief warned. Zero-result queries are listed above because empty output is not evidence that nothing exists.

## The ten photographs

| Slug | Place (county) | Title on Commons | Author | Licence | Commons file page | Source size | Attribution line to show |
|---|---|---|---|---|---|---|---|
| `nairobi-skyline` | Nairobi | Nairobi's Central Business District Landmark Skyscrapers. | Tall Black | CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0) | <https://commons.wikimedia.org/wiki/File:Nairobi%27s_Central_Business_District_Landmark_Skyscrapers..jpg> | 4032 x 2268 | Photo: Tall Black, CC BY-SA 4.0 (resized), via Wikimedia Commons |
| `nairobi-golden-hour` | Nairobi | Aerial view of the Nairobi skyline from the KICC rooftop at golden hour | Lebu Ayiga | CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0) | <https://commons.wikimedia.org/wiki/File:Aerial_view_of_the_Nairobi_skyline_from_the_KICC_rooftop_at_golden_hour.jpg> | 4000 x 3000 | Photo: Lebu Ayiga, CC BY-SA 4.0 (resized), via Wikimedia Commons |
| `nairobi-jacaranda` | Nairobi | Carpet of purple jacaranda blossoms (5112231780) | McKay Savage from London, UK | CC BY 2.0 (https://creativecommons.org/licenses/by/2.0) | <https://commons.wikimedia.org/wiki/File:Carpet_of_purple_jacaranda_blossoms_(5112231780).jpg> | 2048 x 1365 | Photo: McKay Savage from London, UK, CC BY 2.0 (resized), via Wikimedia Commons |
| `mombasa-old-town` | Mombasa | Old Town Mombasa Import Dock | Martin Chomba | CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0) | <https://commons.wikimedia.org/wiki/File:Old_Town_Mombasa_Import_Dock.jpg> | 4032 x 2268 | Photo: Martin Chomba, CC BY-SA 4.0 (resized), via Wikimedia Commons |
| `mombasa-likoni-ferry` | Mombasa | Likoni Ferry (cropped) | Victor Ochieng | CC BY-SA 2.0 (https://creativecommons.org/licenses/by-sa/2.0) | <https://commons.wikimedia.org/wiki/File:Likoni_Ferry_(cropped).jpg> | 2160 x 1215 | Photo: Victor Ochieng, CC BY-SA 2.0 (resized), via Wikimedia Commons |
| `kisumu-lake-victoria` | Kisumu | Lake Victoria as visible from Kisumu City | Yashvi1919 | CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0) | <https://commons.wikimedia.org/wiki/File:Lake_Victoria_as_visible_from_Kisumu_City.jpg> | 2560 x 1440 | Photo: Yashvi1919, CC BY-SA 4.0 (resized), via Wikimedia Commons |
| `nakuru-lake` | Nakuru | Lago Nakuru, Kenia, 2024-05-19, DD 01-03 PAN | Diego Delso | CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0) | <https://commons.wikimedia.org/wiki/File:Lago_Nakuru,_Kenia,_2024-05-19,_DD_01-03_PAN.jpg> | 8684 x 4491 | Photo: Diego Delso, CC BY-SA 4.0 (resized), via Wikimedia Commons |
| `eldoret-town` | Uasin Gishu | Eldoret 1 | Daryona | CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0) | <https://commons.wikimedia.org/wiki/File:Eldoret_1.JPG> | 2300 x 1724 | Photo: Daryona, CC BY-SA 3.0 (resized), via Wikimedia Commons |
| `rongai-market` | Kajiado | Market In Africa | safaritravelplus | CC0 (https://creativecommons.org/publicdomain/zero/1.0/deed.en) | <https://commons.wikimedia.org/wiki/File:Market_In_Africa.jpg> | 3984 x 2656 | Photo: safaritravelplus (CC0, public domain dedication; resized), via Wikimedia Commons |
| `kenya-tea` | Kenya | Tea Farm in Kenya | SeanTwice | CC0 (https://creativecommons.org/publicdomain/zero/1.0/deed.en) | <https://commons.wikimedia.org/wiki/File:Tea_Farm_in_Kenya.jpg> | 4624 x 2084 | Photo: SeanTwice (CC0, public domain dedication; cropped and resized), via Wikimedia Commons |

## Files produced (bytes)

| Slug | 1600 AVIF | 1600 WebP | 800 AVIF | 800 WebP | blur JPG | 1600 x h (as served) |
|---|---|---|---|---|---|---|
| `nairobi-skyline` | 113,959 | 154,890 | 53,235 | 52,946 | 393 | 1600 x 900 |
| `nairobi-golden-hour` | 137,242 | 152,898 | 53,488 | 67,016 | 421 | 1600 x 1200 |
| `nairobi-jacaranda` | 150,840 | 154,098 | 53,473 | 66,572 | 383 | 1600 x 1067 |
| `mombasa-old-town` | 114,316 | 152,830 | 53,050 | 54,784 | 401 | 1600 x 900 |
| `mombasa-likoni-ferry` | 119,665 | 116,100 | 53,173 | 52,388 | 391 | 1600 x 900 |
| `kisumu-lake-victoria` | 152,657 | 149,012 | 51,901 | 67,400 | 427 | 1600 x 900 |
| `nakuru-lake` | 152,959 | 152,824 | 54,038 | 67,644 | 396 | 1600 x 828 |
| `eldoret-town` | 118,071 | 119,402 | 53,930 | 54,028 | 419 | 1600 x 1199 |
| `rongai-market` | 146,727 | 153,238 | 54,964 | 67,778 | 440 | 1600 x 1067 |
| `kenya-tea` | 151,642 | 152,240 | 65,583 | 67,422 | 415 | 1600 x 800 |

## Evidence table

Each row is one fact read from the Commons API response for the file named (`extmetadata` field names as the API returns them). Date read: 2026-10-07 for every row.

| Claim | Quote | URL | Date |
|---|---|---|---|
| `nairobi-skyline`: licence | `LicenseShortName`: "CC BY-SA 4.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/4.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ANairobi%27s%20Central%20Business%20District%20Landmark%20Skyscrapers..jpg | 2026-10-07 |
| `nairobi-skyline`: author | `Artist`: "Tall Black" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ANairobi%27s%20Central%20Business%20District%20Landmark%20Skyscrapers..jpg | 2026-10-07 |
| `nairobi-skyline`: place | Commons categories: Skylines of Nairobi | https://commons.wikimedia.org/wiki/File:Nairobi%27s_Central_Business_District_Landmark_Skyscrapers..jpg | 2026-10-07 |
| `nairobi-golden-hour`: licence | `LicenseShortName`: "CC BY-SA 4.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/4.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AAerial%20view%20of%20the%20Nairobi%20skyline%20from%20the%20KICC%20rooftop%20at%20golden%20hour.jpg | 2026-10-07 |
| `nairobi-golden-hour`: author | `Artist`: "Lebu Ayiga" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AAerial%20view%20of%20the%20Nairobi%20skyline%20from%20the%20KICC%20rooftop%20at%20golden%20hour.jpg | 2026-10-07 |
| `nairobi-golden-hour`: place | Commons categories: Aerial photographs of Nairobi; Views from the tower of Kenyatta International Conference Centre | https://commons.wikimedia.org/wiki/File:Aerial_view_of_the_Nairobi_skyline_from_the_KICC_rooftop_at_golden_hour.jpg | 2026-10-07 |
| `nairobi-jacaranda`: licence | `LicenseShortName`: "CC BY 2.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by/2.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ACarpet%20of%20purple%20jacaranda%20blossoms%20%285112231780%29.jpg | 2026-10-07 |
| `nairobi-jacaranda`: author | `Artist`: "McKay Savage from London, UK" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ACarpet%20of%20purple%20jacaranda%20blossoms%20%285112231780%29.jpg | 2026-10-07 |
| `nairobi-jacaranda`: place | Commons description: "The jacaranda are in bloom in Nairobi and surrounding." | https://commons.wikimedia.org/wiki/File:Carpet_of_purple_jacaranda_blossoms_(5112231780).jpg | 2026-10-07 |
| `mombasa-old-town`: licence | `LicenseShortName`: "CC BY-SA 4.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/4.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AOld%20Town%20Mombasa%20Import%20Dock.jpg | 2026-10-07 |
| `mombasa-old-town`: author | `Artist`: "Martin Chomba" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AOld%20Town%20Mombasa%20Import%20Dock.jpg | 2026-10-07 |
| `mombasa-old-town`: place | Commons category: Port of Mombasa (the file page names no county; Mombasa Old Town is in Mombasa County) | https://commons.wikimedia.org/wiki/File:Old_Town_Mombasa_Import_Dock.jpg | 2026-10-07 |
| `mombasa-likoni-ferry`: licence | `LicenseShortName`: "CC BY-SA 2.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/2.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALikoni%20Ferry%20%28cropped%29.jpg | 2026-10-07 |
| `mombasa-likoni-ferry`: author | `Artist`: "Victor Ochieng" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALikoni%20Ferry%20%28cropped%29.jpg | 2026-10-07 |
| `mombasa-likoni-ferry`: place | Commons category: Mombasa County | https://commons.wikimedia.org/wiki/File:Likoni_Ferry_(cropped).jpg | 2026-10-07 |
| `kisumu-lake-victoria`: licence | `LicenseShortName`: "CC BY-SA 4.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/4.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALake%20Victoria%20as%20visible%20from%20Kisumu%20City.jpg | 2026-10-07 |
| `kisumu-lake-victoria`: author | `Artist`: "Yashvi1919" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALake%20Victoria%20as%20visible%20from%20Kisumu%20City.jpg | 2026-10-07 |
| `kisumu-lake-victoria`: place | Commons category: Kisumu County | https://commons.wikimedia.org/wiki/File:Lake_Victoria_as_visible_from_Kisumu_City.jpg | 2026-10-07 |
| `nakuru-lake`: licence | `LicenseShortName`: "CC BY-SA 4.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/4.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALago%20Nakuru%2C%20Kenia%2C%202024-05-19%2C%20DD%2001-03%20PAN.jpg | 2026-10-07 |
| `nakuru-lake`: author | `Artist`: "Diego Delso" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ALago%20Nakuru%2C%20Kenia%2C%202024-05-19%2C%20DD%2001-03%20PAN.jpg | 2026-10-07 |
| `nakuru-lake`: place | Commons category: Lake Nakuru (the file page names no county; Wikipedia: Lake Nakuru lies south of Nakuru and is protected by Lake Nakuru National Park) | https://commons.wikimedia.org/wiki/File:Lago_Nakuru,_Kenia,_2024-05-19,_DD_01-03_PAN.jpg | 2026-10-07 |
| `eldoret-town`: licence | `LicenseShortName`: "CC BY-SA 3.0"; `LicenseUrl`: "https://creativecommons.org/licenses/by-sa/3.0" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AEldoret%201.JPG | 2026-10-07 |
| `eldoret-town`: author | `Artist`: "Daryona" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AEldoret%201.JPG | 2026-10-07 |
| `eldoret-town`: place | Commons category: Eldoret; Wikipedia: Eldoret "serves as the capital of Uasin Gishu County" | https://commons.wikimedia.org/wiki/File:Eldoret_1.JPG | 2026-10-07 |
| `rongai-market`: licence | `LicenseShortName`: "CC0"; `LicenseUrl`: "http://creativecommons.org/publicdomain/zero/1.0/deed.en" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AMarket%20In%20Africa.jpg | 2026-10-07 |
| `rongai-market`: author | `Artist`: "safaritravelplus" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3AMarket%20In%20Africa.jpg | 2026-10-07 |
| `rongai-market`: place | Commons description: "This market is in ongata rongai, Kenya."; Wikipedia: Ongata Rongai is "in Kajiado North, Kajiado County" | https://commons.wikimedia.org/wiki/File:Market_In_Africa.jpg | 2026-10-07 |
| `kenya-tea`: licence | `LicenseShortName`: "CC0"; `LicenseUrl`: "http://creativecommons.org/publicdomain/zero/1.0/deed.en" | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ATea%20Farm%20in%20Kenya.jpg | 2026-10-07 |
| `kenya-tea`: author | `Artist`: "SeanTwice" (HTML removed) | https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&titles=File%3ATea%20Farm%20in%20Kenya.jpg | 2026-10-07 |
| `kenya-tea`: place | Commons category: Tea plantations in Kenya (no county documented) | https://commons.wikimedia.org/wiki/File:Tea_Farm_in_Kenya.jpg | 2026-10-07 |
| Wikipedia states the county of Eldoret | "It serves as the capital of Uasin Gishu County." | https://en.wikipedia.org/api/rest_v1/page/summary/Eldoret | 2026-10-07 |
| Wikipedia states the county of Ongata Rongai | "Ongata Rongai is a town located in Kajiado North, Kajiado County, Kenya." | https://en.wikipedia.org/api/rest_v1/page/summary/Ongata_Rongai | 2026-10-07 |
| Wikipedia places Lake Nakuru by the town of Nakuru | "It lies to the south of Nakuru, in the rift valley of Kenya and is protected by Lake Nakuru National Park." | https://en.wikipedia.org/api/rest_v1/page/summary/Lake_Nakuru | 2026-10-07 |
| Pillow in the backend venv encodes AVIF and WebP | `PIL.features.check('avif')` and `check('webp')` both returned True; Pillow 12.3.0 | local: `/home/user/second-brain/backend/.venv` | 2026-10-07 |

## Implications for the REQ-IDs

- D-66 and the P24 card (section A): the county photo strip, the Explore county tiles and `/credits` can be built from `frontend/public/photos/index.json` (`slug, county, caption, width, height, credit`); `<picture>` with AVIF then WebP, `<slug>-blur.jpg` as the placeholder (inline as a data URI or `blurDataURL`), widths 800 and 1600. The `county` values are Nairobi, Mombasa, Kisumu, Nakuru, Uasin Gishu, Kajiado and "Kenya" (tea; no county documented). Explore county tiles exist only for counties that have a photograph: Nairobi, Mombasa, Kisumu, Nakuru and Uasin Gishu; Kajiado and the tea photograph suit a niche row or the strip instead.
- Spec 04 principle 4 (no third-party logos, no implied endorsement): no photograph has a brand as its subject; `nairobi-golden-hour` contains small incidental signage on rooftops and a billboard at skyline distance, and `eldoret-town` shows a bus with lettering; the card's ux-reviewer should confirm at 375 and 1440 px. Captions in `index.json` describe the scene only and name no company.
- Acceptance 4 of the P24 card (photographs licensed and credited): the attribution line in `index.json` must be shown on `/credits` (and the footer links it); CC BY and CC BY-SA require attribution, the licence and an indication of changes (the line says "resized" or "cropped and resized"); CC BY-SA also requires derivatives to be shared under the same licence, which `CREDITS.md` states. Whether a caption on every use (not only `/credits`) is needed is not decided here: a credits page linked from the footer is the design in the card.
- Acceptance 2 (Lighthouse, LCP <= 2.5 s on `/`): the hero should not be a 1600 px photograph; the county strip is below the fold, so use `loading="lazy"`, 800 px sources for tiles and the blur placeholder. This is a design note, not a measurement.
- REQ-UX-03 (onboarding asks for county): the same county names are the vocabulary for the picker; the photographs do not change that requirement.

## Open questions

1. Is a "Photo: Author, Licence" line on `/credits` enough, or must each public use of a photograph show it nearby? Not decided in the sources read; CC licence legal codes were not read for this note, only the licence short names and URLs from Commons. Owner/legal review (credits text is legal-adjacent).
2. A Nairobi avenue lined with jacaranda trees was not found with a usable licence in the queries tried; the jacaranda photograph is a carpet of fallen blossoms. A further search (for example categories under Jacaranda mimosifolia in Nairobi) could be run if the owner wants the avenue.
3. A telecom tower and a workshop were not included: the one tower photograph found has no documented place and an advertorial description, and the workshop photographs show workers' faces (model-release status is not stated on the Commons pages read).
4. `eldoret-town` is overcast and a street scene with people at small scale; a brighter photograph of Eldoret was not found with the queries tried.
5. No photograph has an identifiable person as its subject, but the Commons pages read do not state model-release status for the people who appear small in `eldoret-town`, `mombasa-likoni-ferry` and `kisumu-lake-victoria`.
6. The files were produced from Commons' 1920 px thumbnails, not the full-resolution originals (the 1600 px outputs are sharper than 2x displays at half width would need, but not true 2x of a 1600 px slot).
