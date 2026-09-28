# Phase 2 (T2.6a) — Provisional directory seed sources (REQ-DIR-02, D-21)

Checked: 2026-09-27. All URLs fetched or searched on 2026-09-27 unless noted. Rule applied throughout
(D-21, quoted from `DECISIONS-NEEDED.md`): "the provisional directory seed uses public organisational
data only (no personal names, emails or phone numbers), with a source URL and date on every row." No
logos. Every org in `backend/seed/ke_provisional.yaml` is E0 (unclaimed). Where a register could not be
fetched or a fact could not be confirmed, the row (or the field) was skipped rather than guessed — see
"Gaps and open questions" per register and the consolidated list at the end.

Updated 2026-09-28: Safaricom PLC and Airtel Networks Kenya Limited now ship with `official_domains: []` (their
domains were cited only to Wikipedia; see section 1 and open question 10).

## Question

For `backend/seed/ke_provisional.yaml` (Phase 2 provisional directory seed), which public Kenyan
registers list, for the wedge niches, telecom licensees and the 47 county governments: the organisation's
legal name, kind, niche, head-office county, and (only when confirmed on an official source) its
official domain(s)?

## Short answer

Eight registers were fetched successfully as primary or near-primary sources (Communications Authority
of Kenya's Register of Unified Licensing Framework Licensees; Central Bank of Kenya's Directory of
Licenced Microfinance Banks; SASRA's 2026 list of licensed deposit-taking Sacco societies; the Commission
for University Education's list of universities authorised to operate in Kenya; TVETA's register of
accredited TVET institutions; the Office of the President's ministries directory plus four ministries'
own `.go.ke` sites; the Council of Governors' current-governors page; and PBORA's public register of
Public Benefit Organisations). `ca.go.ke`'s own HTML pages and its 2026-dated PDFs are behind a
Cloudflare bot challenge that blocked every automated fetch attempt; the telecom rows instead cite an
older (January 2023) CA register mirrored on `repository.ca.go.ke`, which still lists the three required
telcos and several ISPs by exact legal name — flagged as a G6 open question (re-fetch the 2026 register
manually). The Commission for University Education's own list page is a JavaScript app that returns no
list content to an automated fetch; the university rows instead cite CUE's own August 2022 PDF (data "as
at December 2020"), corroborated against 2026 news/Wikipedia for continued operation. **Basic education
was skipped entirely**: no official Ministry of Education page listing named public national schools
could be found or fetched, and the task card says to skip rather than guess. Official domains are
recorded only where an official source was actually fetched and shows the domain (Telkom Kenya via a
direct fetch of `telkom.co.ke`; microfinance banks via CBK's own PDF; four national ministries via their
own `.go.ke` sites; one county, Kirinyaga, via its own site); every other row carries
`official_domains: []`, including Safaricom PLC and Airtel Networks Kenya Limited, whose domains were
seen only in Wikipedia infoboxes (not an official source).

## Evidence table

### 1. Telecom licensees (niche `networks-telecommunications`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| `ca.go.ke`'s licensee register and its 2026-dated PDFs are not machine-fetchable | Fetch of `https://www.ca.go.ke/licensee-register` and of the 2026-07 and 2026-05 register PDFs on `ca.go.ke` returned only a Cloudflare interstitial: "One moment, please... Please wait while your request is being verified..." | https://www.ca.go.ke/licensee-register ; https://www.ca.go.ke/sites/default/files/2026-07/REGISTER%20OF%20TELECOMMUNICATION%20LICENSEES.pdf ; https://www.ca.go.ke/sites/default/files/2026-05/REGISTER%20OF%20UNIFIED%20LICENSING%20FRAMEWORK%20LICENSEES.pdf | 2026-09-27 |
| An older CA register (mirrored off the main site) lists AIRTEL NETWORKS KENYA LIMITED, JAMII TELECOMMUNICATIONS LIMITED, SAFARICOM PLC and TELKOM KENYA LIMITED as the four Network Facilities Provider Tier One (NFP-T1) licensees | Document header: "REGISTER OF UNIFIED LICENSING FRAMEWORK LICENSEES ... 2022/2023 VER 1. JANUARY 2023"; section "3. NETWORK FACILITIES PROVIDER TIER ONE (1)" lists "1. AIRTEL NETWORKS KENYA LIMITED", "2. JAMII TELECOMMUNICATIONS LIMITED", "3. SAFARICOM PLC", "4. TELKOM KENYA LIMITED" | https://repository.ca.go.ke/server/api/core/bitstreams/4738747b-e721-4afc-9275-ac09f3dabe40/content (PDF, extracted with `pdftotext -layout`; downloaded via the WebFetch tool, converted locally since the tool cannot parse this PDF's compressed text streams) | 2026-09-27 |
| The same register lists WANANCHI TELECOM LIMITED and LIQUID TELECOMMUNICATIONS KENYA LIMITED under International Gateway Operators / NFP-T2, and POA INTERNET KENYA LIMITED and MAWINGU NETWORKS LIMITED under NFP-T3 (ISPs) | Lines: "11. WANANCHI TELECOM LIMITED", "6. LIQUID TELECOMMUNICATIONS KENYA LIMITED" (International Gateway Operators, also re-listed further in the document); "72. POA INTERNET KENYA LIMITED", "60. MAWINGU NETWORKS LIMITED" (NFP-T3 list, town NANYUKI for Mawingu) | same PDF as above | 2026-09-27 |
| Safaricom's domain and full legal name (Wikipedia only: the domain is **not** seeded until an official source confirms it) | Infobox "Website" field: "www.safaricom.co.ke"; article text: "Safaricom PLC" | https://en.wikipedia.org/wiki/Safaricom | 2026-09-27 |
| Airtel Kenya's domain (Wikipedia only: **not** seeded for Airtel Networks Kenya Limited until an official source confirms it) | Infobox "Website" field: "www.airtelkenya.com" | https://en.wikipedia.org/wiki/Airtel_Kenya | 2026-09-27 |
| Telkom Kenya's official domain and current branding | Fetched page footer: "Telkom Kenya © 2026 - All Rights Reserved"; Wikipedia infobox "Website": "http://www.telkom.co.ke/" | https://telkom.co.ke ; https://en.wikipedia.org/wiki/Telkom_Kenya | 2026-09-27 |
| Airtel's Kenyan licence position is currently unsettled (context, not used to exclude the row) | "Airtel Kenya has asked the Communications Authority of Kenya (CA) for two licenses" including "Network Facilities Provider Tier 1 license"; "The article does not indicate that Airtel Kenya currently holds these licenses; rather, it describes these as pending applications under public consultation" | https://techweez.com/2026/08/31/airtel-kenya-nfp-tier-1-license/ | 2026-09-27 |
| Jamii, Wananchi, Liquid, Poa Internet and Mawingu official domains | not found on any source actually fetched | — | 2026-09-27 |

Gaps/open questions for this register: (1) the current (2026-05/2026-07) CA register could not be
fetched automatically — someone with a real browser should re-pull it and diff against the January 2023
list used here before G6; (2) Airtel Networks Kenya Limited's NFP-T1 status is contested in 2026 press
coverage even though it appears in the January 2023 register and AC-DIR-6 requires it under this niche —
included per D-21/AC-DIR-6, flagged for G6; (3) no confirmed domain found for Jamii Telecommunications,
Wananchi Telecom, Liquid Telecommunications Kenya, Poa Internet Kenya or Mawingu Networks — all five ship
with `official_domains: []`; (4) Safaricom's (`safaricom.co.ke`) and Airtel Kenya's (`airtelkenya.com`)
domains are cited only to Wikipedia, which is not an official source. A verification attempt on
2026-09-28 from the build's cloud session could not fetch any official source (web access is blocked
there), so both rows ship with `official_domains: []` until an official citation is recorded; until then a
claim on either organisation gets manual E1 review, not the automatic domain match. Telkom Kenya keeps
`telkom.co.ke`: that domain was fetched directly and its own footer names Telkom Kenya.

### 2. Microfinance banks (niche `microfinance-saccos`, kind `sacco_mfi`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| CBK's February 2026 directory lists 14 licensed microfinance banks with legal name, website and physical address | Directory entries incl. "1. Caritas Microfinance Bank Limited ... Website: www.caritas-mfb.co.ke ... Physical Address: ... Nairobi"; "5. Faulu Microfinance Bank Limited ... Website: www.faulukenya.com"; "6. Kenya Women Microfinance Bank PLC ... Website: www.kwftbank.com"; "9. SMEP Microfinance Bank Limited ... Website: www.smep.co.ke"; "14. Muungano Microfinance Bank PLC ... Physical Address: Eastend Mall Kangari Township, Kangari-Githumu Road" [Murang'a; no website field for this one] | https://www.centralbank.go.ke/wp-content/uploads/2026/02/Directory-of-Licenced-Microfinance-Banks-Feb-2026.pdf (PDF, `pdftotext -layout`) | 2026-09-27 |

Five of the 14 were seeded (Caritas, Faulu, Kenya Women, SMEP — all head-officed in Nairobi per the PDF's
physical address field; Muungano — head-officed in Murang'a). The other nine (Branch, Choice, Umba,
Rafiki, Lolc Kenya, Sumac, U & I, Salaam, On It) were left out only for the "about 5" quota, not for any
data-quality reason; all are equally citable from the same PDF for a later G6 expansion.

### 3. Deposit-taking SACCOs (niche `microfinance-saccos`, kind `sacco_mfi`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| SASRA's gazetted 2026 list names 176 Sacco societies licensed for deposit-taking business, each with a physical head-office location and county | Title: "LIST OF LICENSED AND AUTHORISED SACCO SOCIETIES IN KENYA FOR THE FINANCIAL YEAR ENDING 31ST DECEMBER 2026"; "Schedule I: List of Sacco Societies licensed to undertake deposit-taking business in Kenya for the period 1st January 2026 to 31st December 2026"; table columns "Names of the Deposit Taking SACCO Society / Postal Address / Physical Location of Head Office / County Location of Head Office"; sampled rows incl. "3 Afya Sacco Society Ltd ... Nairobi", "47 Harambee DT Sacco Society Ltd ... Nairobi", "48 Hazina Sacco Society Ltd ... Nairobi", "51 Imarika Sacco Society Ltd ... Kilifi", "33 Egerton University Sacco Society Ltd ... Nakuru" | https://gaa.go.ke/sites/default/files/2026-02/SASRA--LIST%20OF%20LICENSED%20AND%20AUTHORISED%20SACCO%20SOCIETIES%20IN%20KENYA%20FOR%20THE%20FINANCIAL%20YEAR%20ENDING%2031ST%20DECEMBER%202026.pdf (PDF, `pdftotext -layout`) | 2026-09-27 |
| SASRA's own `sasra.go.ke/licensed-dt-saccos/` page did not return usable list content to automated fetch | The page "only displays links to downloadable documents ... the actual content of those files is not visible in the webpage excerpt provided" | https://www.sasra.go.ke/licensed-dt-saccos/ | 2026-09-27 |

The five seeded SACCOs (Afya, Harambee, Hazina, Imarika, Egerton University) were picked for county
spread (Nairobi ×3, Kilifi, Nakuru) from the 176-row Schedule I; no website/domain column exists in this
register, so all five ship with `official_domains: []`.

### 4. Higher education (niche `higher-education`, kind `university_tvet`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| CUE's own list page renders no institution names to an automated fetch | "The page is the homepage of the Commission for University Education (CUE) itself ... the actual document content does not list any individual university names" | https://www.cue.or.ke/index.php/status-of-universities | 2026-09-27 |
| CUE's August 2022 PDF (data "as at December 2020") is a primary, machine-readable source naming public chartered universities, private chartered universities and public university constituent colleges | "UNIVERSITIES AUTHORISED TO OPERATE IN KENYA ... As at December 2020, the list of accredited universities authorised to operate in Kenya is as follows" followed by numbered lists "Public Chartered Universities" (1. University of Nairobi; 2. Moi University; 5. Jomo Kenyatta University of Agriculture and Technology; ...) and "Private Chartered Universities" (2. Catholic University of Eastern Africa (CUEA); 10. Strathmore University; 12. Mount Kenya University; ...); Egerton University appears at position 4 | https://www.cue.or.ke/documents/Accredited_Universities_Kenya_August_2022.pdf (PDF, `pdftotext -layout`) | 2026-09-27 |
| The August 2022 CUE list is dated; Kenya had 36 public chartered universities by 2026 (this document lists 35 plus later additions) | "Bomet University is the 36th Chartered University, chartered on 4 February 2026"; "CUE published the latest list of accredited universities in Kenya as of March 12, 2026" | web search summary, not independently fetched (CUE's current list page would not render — see row above) | 2026-09-27 |
| The eight seeded universities (5 public, 3 private) are corroborated as still-operating institutions by an independent tertiary source | Infobox/list entries for University of Nairobi, Moi University, Kenyatta University, Egerton University, Strathmore University, Catholic University of Eastern Africa, Kabarak University, each with a city/town | https://en.wikipedia.org/wiki/List_of_universities_and_colleges_in_Kenya | 2026-09-27 |

No official domain was confirmed for any of the eight universities (no dedicated fetch of each
university's own site was done in this pass); all eight ship with `official_domains: []` — an open item
for G6 or a later research pass.

### 5. TVET institutions (niche `higher-education`, kind `university_tvet`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| TVETA's own accredited-institutions register lists named, licensed TVET institutions with county and expiry date | "Coastland Professional Training College - Mombasa County"; "Marengoni Community Technical College - Kajiado County"; "These facilities are listed as 'Registered and Licensed' on the TVET Authority's accredited institutions registry, with expiry dates ranging from 2027 to 2031" | https://www.tveta.go.ke/accredited-tvet-institutions/ | 2026-09-27 |

The two seeded TVET institutions are small, specific colleges rather than the well-known national
polytechnics (Kenya Polytechnic, Nairobi Technical Training Institute, etc.); they were picked only
because they were the two entries this fetch actually returned. A later pass should re-query the register
(it appears to be a long, possibly paginated list) for more recognisable institutions. No domains were
confirmed for either.

### 6. National government (niche `national-government`, kind `national_govt`, `public_entity: true`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| The Office of the President lists 22 ministries plus the State Law Office; individual ministry domains are not given on this directory page | "Based on the official presidential website, here are the 22 ministries displayed" (list incl. "Ministry of Interior and National Administration", "The National Treasury and Economic Planning", "Ministry of Health", "Ministry of Education", "Ministry of Agriculture and Livestock Development"); "Individual ministry website domains are not specified in the provided content" | https://www.president.go.ke/ministries-ke/ | 2026-09-27 |
| Ministry of Health's own site confirms its name and domain | Footer: "© Copyright 2022 \| Ministry of Health \| All Rights Reserved"; header "MoH \| Ministry of Health" | https://www.health.go.ke/ | 2026-09-27 |
| Ministry of Education's own site confirms its name and domain | Footer: "© Copyright 2023. Ministry of Education. All Rights Reserved."; page title "Homepage \| Ministry of Education - Kenya" | https://www.education.go.ke/ | 2026-09-27 |
| The National Treasury's own site confirms its name and domain | Footer: "© Copyright The National Treasury 2026. All Rights Reserved."; Facebook link references "The National Treasury and Economic Planning" | https://www.treasury.go.ke/ | 2026-09-27 |
| Ministry of Agriculture and Livestock Development's own site confirms its name and domain | Footer: "Copyright © 2026 \| Ministry of Agriculture and Livestock Development"; "referenced by its Swahili domain name 'kilimo.go.ke'" | https://www.kilimo.go.ke/ | 2026-09-27 |

Ministry of Interior and National Administration is seeded from the president.go.ke directory only; its
own domain (candidates seen in search snippets: `interior.go.ke`, `immigration.go.ke`) was not
independently confirmed by a fetch, so it ships with `official_domains: []` — flagged for G6.

### 7. County governments (niche `county-government`, kind `county_govt`, `public_entity: true`, all 47)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| The Council of Governors' current-governors page names all 47 counties, matching `backend/seed/reference.yaml`'s county list and Phase 1's confirmed First-Schedule ordering | Full 47-row list "1. Mombasa ... 47. Nairobi" (page uses "Nairobi"; `reference.yaml`, sourced from the constitutional First Schedule, uses "Nairobi City" — the seed keeps `reference.yaml`'s name for consistency with the region table) | https://cog.go.ke/current-governors/ | 2026-09-27 |
| Kirinyaga County's own site confirms its official legal name and is reachable at `kirinyaga.go.ke` | "The exact name of the county government shown on this site is 'County Government of Kirinyaga', which appears consistently throughout the header, footer, and branding elements" | https://kirinyaga.go.ke/ | 2026-09-27 |

All 47 rows use `legal_name: "County Government of <name>"` and the `county` code from
`backend/seed/reference.yaml` (ISO 3166-2:KE code, **not** the First-Schedule `county_code` — see that
file's header warning). Only Kirinyaga carries a confirmed `official_domains` entry
(`kirinyaga.go.ke`); the other 46 ship with `official_domains: []`. Confirming the rest (ideally via each
county's own site, or a Council of Governors page that links all 47 sites) is the single largest
mechanical gap in this seed and is listed as an open question below.

### 8. Social/NGO (niche `social-ngo`, kind `ngo_pbo`)

| Claim | Quote | URL | Date read |
|---|---|---|---|
| PBORA's public register lists (per its own homepage counter) over 14,000 registered PBOs, with a searchable/browsable list at `/pbos` | "14687 +" registered PBOs and "9609 +" active PBOs; "The main navigation includes a 'List of PBOs' link" | https://www.pbora.go.ke/ | 2026-09-27 |
| The `/pbos` register, when queried, confirms specific named organisations, including a name-change record for Amref | "AFRICAN MEDICAL AND RESEARCH FOUNDATION (AMREF): CHANGED NAME TO: AMREF HEALTH AFRICA IN KENYA"; "ACTION-AID KENYA"; "ACTIONAID INTERNATIONAL-AFRICA REGIONAL OFFICE" with reference "218/051/924"; "ACTION AID AFRICA" with reference "218/051/2012/0382" | https://www.pbora.go.ke/pbos | 2026-09-27 |
| Other alphabetically early entries on the same register, used as additional rows | "ACTION AFRICA HELP KENYA"; "ACADEMIA HEALTH AND AGRICULTURAL DEVELOPMENT INITIATIVE (AHADI)" | https://www.pbora.go.ke/pbos | 2026-09-27 |

The register gives no county or domain field for any entry in what this fetch returned, so all five
seeded NGO/PBO rows ship with `county: null` and `official_domains: []`.

## Implications for REQ-IDs

- **REQ-DIR-02 / AC-DIR-3, AC-DIR-6**: `backend/seed/ke_provisional.yaml` contains Safaricom PLC, Airtel
  Networks Kenya Limited and Telkom Kenya Limited under `networks-telecommunications`, satisfying
  AC-DIR-6; every row is E0 with a `source_url` and `source_retrieved_on`, satisfying the D-21 rule that
  AC-DIR-3 (badge text, no logos) depends on.
- **AC-DIR-5**: the seed covers Microfinance & SACCOs, Higher education (incl. an org-type distinction
  that the loader will need to map to School/University-TVET), National government, County government and
  Social/NGO — **except Basic education, which is empty by design** (see below); the loader/AC-DIR-5 test
  should not assert a seeded School row until a Ministry of Education source is found.
- **Claim flow (docs/spec/06.2, `official_domains[]`)**: only Telkom, four microfinance banks, four
  national ministries and one county (Kirinyaga) carry a confirmed domain; every other row's
  `official_domains: []` (Safaricom's and Airtel's included, until open question 10 is closed) means any
  claim on those orgs falls to **manual E1 review** rather than automatic domain-match E1, which is the
  safe default per docs/spec/06.2's own fallback rule.
- **G6 production list**: this provisional file is explicitly not the production list (per the file's own
  header and `status: provisional-until-G6`); the gaps below are the primary G6 agenda items.

## Open questions for G6

1. Re-fetch the Communications Authority of Kenya's current (2026-05/2026-07) Register of Unified
   Licensing Framework Licensees with a real browser (the site returns a Cloudflare bot challenge to
   automated tools) and confirm the telecom rows, especially Airtel Networks Kenya Limited's NFP-T1 status
   given the August 2026 press coverage of a pending renewal/permit process.
2. Confirm official domains for Jamii Telecommunications, Wananchi Telecom, Liquid Telecommunications
   Kenya, Poa Internet Kenya and Mawingu Networks.
3. Re-fetch the Commission for University Education's current (2026) list — the August 2022 PDF used
   here is dated "as at December 2020"; confirm the 36th public chartered university (Bomet University,
   per 2026 press) and any private-university changes, and confirm domains for all eight seeded
   universities.
4. Re-query TVETA's accredited-institutions register for more widely recognised TVET institutions (this
   pass only surfaced two small colleges); confirm whether the register is paginated and how to browse it
   systematically.
5. Confirm official domains for 46 of the 47 counties (only Kirinyaga was individually confirmed); decide
   whether the Council of Governors or another single register conveniently lists all 47 domains, or
   whether each county site must be checked individually.
6. Confirm an official domain for Ministry of Interior and National Administration.
7. Find and fetch an authoritative Ministry of Education (or Teachers Service Commission / KNEC) page
   naming specific public national schools before adding any Basic education rows — none was found in
   this pass, so the niche has zero seeded rows.
8. PBORA's register gives no county field; decide whether county should be back-filled from each NGO's
   own site (out of scope for this pass) or left `null` in the production list too.
9. The SASRA Schedule I register gives no domain/website column; decide whether SACCO domains are worth
   sourcing individually (e.g., from each SACCO's own site) for the production list.
10. **Before G6:** cite an official source for `safaricom.co.ke` (Safaricom PLC) and `airtelkenya.com`
    (Airtel Networks Kenya Limited), such as the operator's own site or a regulator or exchange filing that
    names the domain, and only then restore them to `official_domains`. Both are cited only to Wikipedia; a
    verification attempt on 2026-09-28 from the build's cloud session could not fetch any official source
    (web access is blocked there). Until then the E1 domain match stays manual for both organisations.
