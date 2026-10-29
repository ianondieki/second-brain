# Phase 1 (T1.4) — Seed reference data: holidays, counties, ISIC niches

Checked: 2026-09-24. All URLs fetched/searched on 2026-09-24 unless noted.

## Question

For `backend/seed/reference.yaml` (Phase 1 seed), what are: (1) Kenyan public holidays for 2026 and
2027 with dates, the Sunday-observance rule, and moon-sighting caveats for Islamic holidays; (2) the
47 Kenyan counties with their official First-Schedule county code (001–047) and their ISO 3166-2:KE
code, and whether the two numbering schemes align; (3) ISIC Rev.4 codes for the platform's niche list?

## Short answer

- **Holidays**: 12 gazetted holidays/year under the Public Holidays Act (Cap. 110). Section 4 of the Act
  moves a Part I holiday that falls on a **Sunday** to the next non-holiday day (Monday, normally) — it
  does **not** move holidays that fall on a Saturday. For 2026, `Idd-ul-Fitr` (20 Mar) and `Idd-ul-Azha`
  (27 May) are already gazetted (this research happens after both dates in 2026), so they are marked
  `provisional: false`. Three 2026 fixed dates fall on Saturday (Mazingira Day, Jamhuri Day) with no
  shift, per the Sunday-only rule. For 2027, three fixed dates fall on Sunday and shift to Monday:
  Mazingira Day (10→observed 11 Oct), Jamhuri Day (12→observed 13 Dec), Boxing Day (26→observed 27 Dec).
  2027 Idd-ul-Fitr and Idd-ul-Azha are calendar-projection estimates only (moon sighting not yet done) —
  `provisional: true`.
- **Counties**: The First-Schedule constitutional numbering (001 Mombasa … 047 Nairobi City) and the
  ISO 3166-2:KE code list are **different orderings** — ISO 3166-2:KE is alphabetical (KE-01 Baringo …
  KE-47 West Pokot), not the constitutional order. **They do not align.** `backend/seed/reference.yaml`
  carries both `county_code` (First Schedule, "001"–"047") and `code` (ISO, "KE-01"–"KE-47") per county,
  joined by name — do not assume `KE-0N` ↔ county_code `00N`.
- **ISIC Rev.4**: codes found for all 12 requested niches at UNSD's ISIC Rev.4 explorer (see evidence
  table). Two findings needing a product decision: (a) ISIC has no single class combining "networks and
  telecommunications" more specific than division `J 61 Telecommunications` — the child niche reuses the
  parent's code; (b) ISIC does not distinguish government levels — "National government" and "County
  government" both map to class `8411 General public administration activities`; there is no ISIC
  concept of sub-national administration, so the platform's distinction is not representable in ISIC
  alone (flag for a product decision, not an ISIC gap to "fix").

## Evidence table

### 1. Public Holidays Act — legal rule

| Claim | Quote | URL | Date read |
|---|---|---|---|
| Sunday-shift rule, Section 4 | "Where, in any year, a day in Part I of the Schedule falls on a Sunday, then the first succeeding day, not being a public holiday, shall be a public holiday and the first-mentioned day shall cease to be a public holiday." | https://mwakili.com/resources/legal-docs-plain-text/PublicHolidaysActCap110 (plain-text extraction of Cap. 110; the primary kenyalaw.org PDF at https://www.kenyalaw.org/kl/fileadmin/pdfdownloads/Acts/PublicHolidaysActCap110.pdf and the New Kenya Law akn text at https://new.kenyalaw.org/akn/ke/act/1912/21/eng@2024-04-26 both returned HTTP 403 to automated fetch and could not be quoted directly — treat the mwakili quote as **unverified against the primary source** until someone re-checks kenyalaw.org manually) | 2026-09-24 |
| Act structure (Part I general holidays incl. New Year, Good Friday, Easter Monday, Labour Day, Madaraka Day, Idd-ul-Fitr, [renamed] Mazingira Day, [renamed] Mashujaa Day, [renamed] Jamhuri Day, Christmas, Boxing Day; Part II Idd-ul-Azha; Part III Diwali) | "Part I... Part II (Islamic faith): Idd-ul-Azha... Part III (Hindu faith): Diwali" | same mwakili URL (note: this mirror still uses the pre-rename names Moi Day/Kenyatta Day/Independence Day, i.e. it reflects an older consolidation predating the 2010s/2024 renames — names below use the current gazetted names, only the Sunday-shift mechanism and Part-I/II/III structure are taken from this source) | 2026-09-24 |
| Mazingira Day created by amendment, effective 10 October, replacing Utamaduni Day | "The Bill amends the Public Holidays Act (Cap. 110) to substitute Utamaduni Day with Mazingira Day as a public holiday to be observed on 10th October every year." | https://www.citizen.digital/news/utamaduni-day-renamed-to-mazingira-day-as-ruto-signs-new-law-n340968 ; corroborated by https://nation.africa/kenya/news/education/it-s-official-october-10-public-holiday-renamed-mazingira-day-4601562 | 2026-09-24 |
| Amending instrument and assent date | "The renaming of Utamaduni Day to Mazingira Day was effected in April 2024 after President William Ruto assented to the Statute Law (Miscellaneous Amendments) Bill." | https://www.the-star.co.ke/news/2025-10-10-how-october-10-utamaduni-day-was-renamed-mazingira-day | 2026-09-24 |
| Islamic holidays gazetted only after Chief Kadhi confirms moon sighting; dates can shift from any printed calendar | "The Muslim holidays, Idd-ul-Fitr and Idd-ul-Azha, are gazetted by the Interior Cabinet Secretary only once the Chief Kadhi confirms the moon, so they can shift a day from any printed calendar." | https://smarthr.co.ke/blog/kenya-public-holidays-2026 | 2026-09-24 |
| 2026 Idd-ul-Fitr gazetted for Friday 20 March 2026 | "Interior CS Kipchumba Murkomen making the declaration through a Gazette notice... Gazette Notice No. 3955" | https://www.the-star.co.ke/news/2026-03-19-state-declares-friday-public-holiday-to-mark-idd | 2026-09-24 |
| 2026 Idd-ul-Azha gazetted for Wednesday 27 May 2026, under s.3(1) of the Act | "Interior CS Kipchumba Murkomen declared Wednesday, May 27, 2026 a public holiday to mark Eid ul-Adha. The notice was published in a special issue of the Kenya Gazette dated May 25, 2026, under Section 3(1) of the Public Holidays Act." | https://citizen.digital/article/govt-declares-may-27-public-holiday-to-mark-eid-ul-adha-n383374 (corroborated: https://www.capitalfm.co.ke/news/2026/05/govt-declares-wednesday-public-holiday-to-mark-eid-ul-adha/ , https://eastleighvoice.co.ke/news/356685/government-declares-wednesday-may-27-public-holiday-to-mark-eid-al-adha) | 2026-09-24 |
| 2026 fixed-date holidays and weekdays (New Year Thu 1 Jan; Good Friday Fri 3 Apr; Easter Monday Mon 6 Apr; Labour Day Fri 1 May; Madaraka Day Mon 1 Jun; Mazingira Day Sat 10 Oct; Mashujaa Day Tue 20 Oct; Jamhuri Day Sat 12 Dec; Christmas Fri 25 Dec; Boxing Day Sat 26 Dec) | full 2026 list incl. weekdays | https://calendarific.com/holidays/2026/KE | 2026-09-24 — independently re-derived every weekday by manual day-counting from a Wed 2025-01-01 anchor and all matched; no discrepancies found |
| 2027 fixed-date holidays and weekdays, incl. three Sunday-shifts (Mazingira Day Sun 10 Oct → observed Mon 11 Oct; Jamhuri Day Sun 12 Dec → observed Mon 13 Dec; Boxing Day Sun 26 Dec → observed Mon 27 Dec) | full 2027 list incl. "Day off for Mazingira Day — Monday, October 11" and "Jamhuri Day Observed — Monday, December 13" and "Day off for Boxing Day — Monday, December 27" | https://calendarific.com/holidays/2027/KE | 2026-09-24 — independently re-derived weekdays by manual day-counting; all three Sunday flags confirmed by calculation (Oct 10, Dec 12, Dec 26 2027 are each 2 weekdays after a confirmed Fri 2027-01-01 anchor, landing on Sunday) |
| 2027 Idd-ul-Fitr / Idd-ul-Azha are provisional calendar projections, not yet gazetted | "Ramadan Start (Provisional) — Monday, February 8... Idd ul-Fitr (Provisional) — Wednesday, March 10... Eid al-Adha (Provisional) — Monday, May 17... These dates may be modified as official changes are announced, particularly for the provisional Islamic holidays." | https://calendarific.com/holidays/2027/KE | 2026-09-24 |
| Good Friday / Easter Monday 2026 and 2027 dates | "Good Friday Friday, April 3 [2026]... Easter Monday Monday, April 6 [2026]"; "Good Friday Friday, March 26 [2027]... Easter Monday Monday, March 29 [2027]" | https://calendarific.com/holidays/2026/KE and https://calendarific.com/holidays/2027/KE | 2026-09-24 |

### 2. Counties: two numbering schemes, not aligned

| Claim | Quote | URL | Date read |
|---|---|---|---|
| First-Schedule constitutional order, counties 1–47 (Mombasa=1 … Nairobi City=47) | "1. Mombasa 2. Kwale 3. Kilifi ... 47. Nairobi City" | https://klrc.go.ke/index.php/constitution-of-kenya/163-schedules-schedules/165-first-schedule-counties/434-1-counties | 2026-09-24 |
| Official three-digit county code convention follows this same order | "The county numbers follow the order in which the counties appear in the First Schedule of the Constitution of Kenya... Mombasa is 001, while Nairobi is 047." | https://nairobikenya.org/kenya-county-numbers/ | 2026-09-24 |
| ISO 3166-2:KE code list is **alphabetical**, not constitutional (KE-01=Baringo … KE-47=West Pokot; Mombasa=KE-28, Nairobi City=KE-30) | Wikipedia table "KE-01 Baringo ... KE-28 Mombasa ... KE-30 Nairobi City ... KE-47 West Pokot"; "These codes were established following the 2014-10-30 update, which replaced the former eight provincial codes." | https://en.wikipedia.org/wiki/ISO_3166-2:KE | 2026-09-24 |
| **Finding: the ISO order does NOT match the constitutional numbering.** Task assumption to "confirm the ISO list order matches the constitutional numbering" is false — do not encode `KE-0N` as equivalent to county_code `00N`. | (derived from the two rows above; e.g. constitutional #1 is Mombasa but ISO KE-01 is Baringo) | (both URLs above) | 2026-09-24 |

`verified: false` note: I did not independently fetch the ISO 3166 Maintenance Agency's own online browsing
platform (`iso.org`/`www.iso.org/obp`) because it requires an interactive session; the Wikipedia ISO_3166-2:KE
table is used as a secondary source for the code list and should be spot-checked against ISO's OBP or a
paid ISO 3166-2 reference before this table is treated as authoritative for legal/compliance use.

### 3. ISIC Rev.4 codes (UNSD)

All rows from UNSD's ISIC Rev.4 explorer, structure list at
`https://unstats.un.org/unsd/classifications/Econ/Structure?cl=27` and per-code detail pages at
`https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/<code>`, read 2026-09-24.

| Niche (parent › child) | Code | Title (UNSD) | Level | URL |
|---|---|---|---|---|
| Financial services | K 64 | Section K "Financial and insurance activities"; Division 64 "Financial service activities, except insurance and pension funding" | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/6492 (parent hierarchy shown on this page) |
| › Microfinance & SACCOs | 6492 | "Other credit granting" — Group 649 "Other financial service activities, except insurance and pension funding activities" | class | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/6492 |
| ICT | J 61 | Section J "Information and communication"; Division 61 "Telecommunications" | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/61 |
| › Networks & Telecommunications | 61 | Same as parent — division 61 has groups 611 Wired, 612 Wireless, 613 Satellite, 619 Other telecommunications activities, but **no single class combines "networks and telecom"** more specifically than the division; reuse `61` for the child or pick a group (611/612) once product defines "networks" scope | division (no finer single code) | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/61 |
| Education | P 85 | Section P "Education"; Division 85 "Education" | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8530 and .../8510 (parent hierarchy shown) |
| › Higher education | 8530 | "Higher education" — Group 853 "Higher education" | class | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8530 |
| › Basic education | 8510 | "Pre-primary and primary education" — Group 851 "Pre-primary and primary education" | class | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8510 |
| Public sector | O 84 | Section O "Public administration and defence; compulsory social security"; Division 84 same title | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8411 (parent hierarchy shown) |
| › National government | 8411 | "General public administration activities" — Group 841 "Administration of the State and the economic and social policy of the community" | class | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8411 |
| › County government | 8411 | **Same code as National government** — ISIC Rev.4 does not distinguish government levels (national vs. sub-national/county); flag for a product decision, this is not resolvable by picking a different ISIC code | class (ambiguous) | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/8411 |
| Health | Q 86 | Section Q "Human health and social work activities"; Division 86 "Human health activities" (groups 861 Hospital, 862 Medical/dental practice, 869 Other) | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/86 |
| Agriculture | A 01 | Section A "Agriculture, forestry and fishing"; Division 01 "Crop and animal production, hunting and related service activities" | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/01 |
| Energy | D 35 | Section D "Electricity, gas, steam and air conditioning supply"; Division 35 same title (groups 351 Electric power, 352 Gas, 353 Steam/AC) | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/35 |
| Logistics | H 52 | Section H "Transportation and storage"; Division 52 "Warehousing and support activities for transportation" (521 Warehousing/storage, 522 Transport support incl. cargo handling, agencies) | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/52 |
| Retail | G 47 | Section G "Wholesale and retail trade; repair of motor vehicles and motorcycles"; Division 47 "Retail trade, except of motor vehicles and motorcycles" | section+division | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/47 |
| Social/NGO | S 9499 | Section S "Other service activities"; Division 94 "Activities of membership organizations"; Group 949 "Activities of other membership organizations"; Class 9499 "Activities of other membership organizations n.e.c." (scope note explicitly covers "organizations furthering public causes through education and advocacy, including environmental movements... grant-giving by membership entities") | class | https://unstats.un.org/unsd/classifications/Econ/Detail/EN/27/9499 |

`verified: false` note on Logistics: division `H 52` is the closest single division ("warehousing and
support activities for transportation"), but a courier/last-mile logistics business could equally sit in
division 49 (land transport) or 53 (postal and courier activities) — flag for a product decision on which
ISIC class(es) the "Logistics" niche is meant to capture; I did not guess a narrower class without a
product definition of what "Logistics" niche members actually do.

## Implications for REQ-IDs

- **T1.4 / directory & profile seed data (docs/spec/06 directory, region/niche taxonomy)**: use
  `backend/seed/reference.yaml` as-is for regions (country + 47 counties) and niches; both `county_code`
  and ISO `code` are carried per county so the directory can display either without recomputing.
- **Holiday-aware features (reminders/tracker cadence, docs/spec/06.9 tracker, 06.10 reminders)**: treat
  `provisional: true` holidays (2027 Idd-ul-Fitr, 2027 Idd-ul-Azha) as best-effort placeholders; do not
  hard-fail a scheduling feature on them, and re-run this research (or re-seed) once each is gazetted
  (historically within ~1–2 months before the date, per the 2026 gazette-notice timing observed above).
- **County government vs national government niche (06 directory taxonomy)**: needs a human/product
  decision — ISIC alone cannot distinguish them; either accept the shared `8411` code for both or invent
  a platform-local sub-code (would then be `verified: false` against ISIC, true against no external
  standard).
- **Compliance/legal text referencing the Public Holidays Act (docs/spec/10 Kenyan compliance)**: the
  Section 4 quote here is sourced from a secondary mirror because the primary kenyalaw.org URLs 403'd to
  automated fetch; anyone drafting user-facing legal copy citing "Section 4" should manually re-verify
  against kenyalaw.org or the Kenya Gazette before publishing (see open questions).

## Open questions

1. Can someone with interactive browser access confirm the exact Section 4 wording on the primary
   kenyalaw.org Cap. 110 page (both URLs 403'd to this automated fetch)?
2. Should "Logistics" map to ISIC `H 52` (warehousing/transport support) only, or should it also include
   `H 49` (land transport) / `H 53` (postal and courier), depending on what businesses the niche is meant
   to onboard?
3. How should "County government" be represented given ISIC has no sub-national-government code — same
   `8411` as national, or a platform-local extension code outside ISIC?
4. Should the ISO 3166-2:KE table be re-verified against ISO's own Online Browsing Platform (not just
   Wikipedia) before any compliance-sensitive use?
5. Has Idd-ul-Azha 2026 gazette notice number (analogous to Gazette Notice No. 3955 for Idd-ul-Fitr) been
   confirmed anywhere besides the news reports cited above? News sources agree on the date (27 May 2026)
   and cite "Section 3(1)" and a Gazette dated 25 May 2026, but I did not find the notice number itself.
