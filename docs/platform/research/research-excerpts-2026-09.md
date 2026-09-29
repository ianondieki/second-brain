# Research excerpts for the research agent (P11, REQ-RES-01/02), Kenya, 2026-09

Retrieved 2026-09-29. Read-only research; no accounts, credentials or authenticated endpoints; TLS verification never disabled.

## Question

Which short, dated, public excerpts from allowlisted Kenyan sources can be saved in the repo (fetched once at build
time, no runtime scraping) so the P11 research agent can draft problem cards from 3-5 excerpts per niche, with each
quote checkable verbatim against saved text?

## Short answer

19 excerpts saved in `backend/seed/research_excerpts.yaml` across 4 niches (slugs from `backend/seed/reference.yaml`):
`networks-telecommunications` 5, `agriculture` 4, `health` 5, `microfinance-saccos` 5. Every quote was copied from
text extracted from the fetched page and checked programmatically: it occurs exactly once in the whitespace-normalised
extracted text and is 12-41 words (limit 60). Every `published_date` is a date stated by the page itself (a page
metadata field such as `article:published_time`/`datePublished`, or a printed date). Mix: 6 official, 13 news, 0 filing,
0 ngo (see open questions).

## Method

1. Discovery with the WebSearch tool only; search summaries were never used as quotes or dates.
2. Each page fetched once on 2026-09-29 with `curl -L` (User-Agent `Mozilla/5.0 (compatible; BridgeResearchBot/0.1)`),
   after reading the host's `/robots.txt`. No host disallowed the paths used (hosts disallow only admin/system paths, or
   `Disallow: /` for SemrushBot/AhrefsBot only, e.g. capitalfm.co.ke). Business Daily disallows `/kenya/`, `/ke/` etc.,
   not the `/bd/` paths used.
3. HTML converted to text (scripts/styles removed, tags stripped, entities unescaped, whitespace collapsed); PDFs via
   `pypdf`. Extraction scripts and page copies live in the session scratchpad only and are not committed (pages are
   third-party copyright; only the short quotes are stored).
4. Quotes copied from the extracted text (curly apostrophes and en dashes kept as on the page); a check script asserted
   each occurs exactly once after whitespace normalisation, is <= 60 words, and that the ISO `published_date` string
   appears in the fetched HTML.
5. `source_type` follows spec 6.5 tiers: official 1.0, filing 0.9, news/ngo 0.8. No blogs or social.
6. Sources without a page date were skipped.

## Evidence table (claim | quote | URL | date)

Each row: claim = the excerpt exists on the page with this date; the full quote is in the YAML (same `id`), read 2026-09-29.

| id | niche | publisher | type | published (page) | URL | topic |
|---|---|---|---|---|---|---|
| ke-tel-001 | networks-telecommunications | Business Daily | news | 2026-04-03 | https://www.businessdailyafrica.com/bd/corporate/technology/safaricom-grip-loosens-as-airtel-starlink-gain-ground-5412426 | Mobile money market share shifting from M-Pesa to Airtel Money |
| ke-tel-002 | networks-telecommunications | Business Daily | news | 2026-02-27 | https://www.businessdailyafrica.com/bd/corporate/companies/safaricom-takes-another-hit-as-interconnection-rates-fall-by-27pc-5374494 | CA phased cut to mobile termination rates to March 2029 |
| ke-tel-003 | networks-telecommunications | Business Daily | news | 2026-04-07 | https://www.businessdailyafrica.com/bd/corporate/technology/starlink-rivals-face-sh15m-licence-under-new-telecoms-rules-5415310 | New satellite licensing cost under revised telecom market structure |
| ke-tel-004 | networks-telecommunications | Capital FM Kenya | news | 2026-01-16 | https://www.capitalfm.co.ke/business/2026/01/airtel-pushes-for-call-rate-reforms-as-treasury-defends-single-bidder-safaricom-sale/ | Smaller operators say termination charges hinder competition |
| ke-tel-005 | networks-telecommunications | Communications Authority of Kenya | official | 2023-11-19 | https://www.ca.go.ke/consumers-enjoy-lower-calling-rates-following-drop-interconnection-rates | CA cap on mobile and fixed termination rates from March 2024 (background) |
| ke-agr-001 | agriculture | The Standard | news | 2026-08-26 | https://www.standardmedia.co.ke/rift-valley/article/2001556174/state-cuts-fertiliser-and-maize-seed-after-dry-spell-causes-massive-losses | Drought crop failure and projected fall in food production |
| ke-agr-002 | agriculture | The Star | news | 2026-08-23 | https://www.the-star.co.ke/news/2026-08-23-ruto-cuts-fertiliser-price-to-sh2000-in-new-relief-for-farmers | Planned maize imports after reduced production |
| ke-agr-003 | agriculture | Ministry of Agriculture and Livestock Development | official | 2026-09-08 | https://kilimo.go.ke/ps-ronoh-flags-off-99000-metric-tonnes-of-subsidised-fertiliser-at-the-port-of-mombasa/ | Subsidised fertiliser price per 50 kg bag |
| ke-agr-004 | agriculture | Ministry of Agriculture and Livestock Development | official | 2025-02-06 | https://kilimo.go.ke/strengthening-integrity-in-kenyas-subsidized-fertilizer-program/ | Integrity risk in subsidised fertiliser distribution (background) |
| ke-hlt-001 | health | Capital FM Kenya | news | 2026-01-28 | https://www.capitalfm.co.ke/business/2026/01/audit-fake-claims-cost-sha-sh11bn-in-losses/ | Audit finds Sh11 billion fraudulent SHA claims |
| ke-hlt-002 | health | The Star | news | 2026-01-28 | https://www.the-star.co.ke/news/2026-01-28-duale-sha-blocked-sh11bn-in-suspected-fraudulent-claims | Health CS says SHA rejected fraudulent claims (differs from 'lost' framing) |
| ke-hlt-003 | health | The Standard | news | 2026-09-01 | https://www.standardmedia.co.ke/health/health-science/article/2001556702/hospitals-get-one-more-month-on-sha-digital-compliance-rules | Providers must integrate systems with national digital health infrastructure |
| ke-hlt-004 | health | The Standard | news | 2026-09-28 | https://www.standardmedia.co.ke/health/health-science/article/2001558860/health-care-providers-have-until-september-30-to-renew-sha-contracts | SHA 2026-2029 provider contract renewal deadline |
| ke-hlt-005 | health | The Star | news | 2026-07-01 | https://www.the-star.co.ke/news/2026-07-01-sha-shifts-level-4-public-hospitals-to-taifa-care-hmis | Level 4 public hospitals move to Taifa Care HMIS for claims |
| ke-sac-001 | microfinance-saccos | Capital FM Kenya | news | 2026-09-28 | https://capitalfm.africa/saccos-deposits-rise-11-12pc-to-sh832-74bn-as-assets-hit-sh1-21tn/ | Regulated SACCO assets growth in 2025 |
| ke-sac-002 | microfinance-saccos | Business Daily | news | 2026-03-03 | https://www.businessdailyafrica.com/bd/corporate/companies/sacco-loans-default-rate-falls-to-5-9pc-on-improved-payment-5378710 | SACCO non-performing loan ratio near 5 percent benchmark |
| ke-sac-003 | microfinance-saccos | SACCO Societies Regulatory Authority (SASRA) | official | 2026-07-16 | https://www.sasra.go.ke/2026/07/16/strengthening-cyber-resilience-in-the-sacco-industry/ | SASRA focus on cyber resilience in SACCOs |
| ke-sac-004 | microfinance-saccos | SACCO Societies Regulatory Authority (SASRA) | official | 2026-06-15 | https://www.sasra.go.ke/2026/06/15/sasra-conducts-the-2026-regulatory-policy-and-legal-roundtable-for-deposit-taking-saccos/ | Regulatory issues for deposit-taking SACCOs |
| ke-sac-005 | microfinance-saccos | SACCO Societies Regulatory Authority (SASRA) | official | 2026-06-25 | https://www.sasra.go.ke/2026/06/25/cs-oparanya-calls-on-sasra-to-strengthen-capacity-and-prepare-for-expanded-mandate/ | Proposed expansion of SASRA regulatory mandate |

Where the page states its date: Business Daily `og:article:published_time`; Capital FM `article:published_time`;
The Standard and The Star `datePublished` (JSON-LD); MoALD `article:published_time` and printed date; SASRA
`<time class="entry-date published" datetime=...>`; CA press page printed "Sun, 11/19/2023" / "November 19, 2023".

## Sources tried and not used

| Source | Result (2026-09-29) | Why not used |
|---|---|---|
| https://www.knbs.or.ke/reports/2026-economic-survey/ and the `2026-Economic-Survey.pdf` (KNBS) | curl error 60 "unable to get local issuer certificate" (server sends an incomplete chain); also not reachable with a bare host request | Failed; verification not bypassed. Retry when KNBS fixes its chain or the CA bundle is extended by the human |
| https://nation.africa/kenya/counties/cheaper-fertiliser-seeds-offer-lifeline-to-farmers-hit-by-maize-losses-5570014 and `.../drought-hit-farmers-wary-of-replanting-5584172` | HTTP 403 (bot block) | Failed; not worked around |
| https://www.sasra.go.ke/2025/09/25/sasra-releases-the-2024-sacco-supervision-annual-report/ and https://www.sasra.go.ke/download/the-sacco-supervision-annual-report-2024/ | HTTP 404 (URLs came from search results and do not exist on the live site) | Failed |
| https://www.health.go.ke/cs-duale-leads-consultative-forum-transition-sha-hmis | timeout after 60 s | Failed |
| https://www.centralbank.go.ke/uploads/market_perception_surveys/1904898339_Agriculture%20Survey%20May%202026.pdf (CBK) | 200 after one retry | Page states only "May 2026", no day; skipped per "date from the page" |
| https://www.ca.go.ke/sites/default/files/2026-04/Sector%20Statistics%20Report%20Q2%202025-2026.pdf (CA) and https://www.ca.go.ke/statistics | 200 | Neither the PDF nor the listing prints a publication date (PDF metadata `CreationDate` 2026-04-02 only); skipped |
| https://www.centralbank.go.ke/uploads/press_releases/1035898107_Press%20Release%20-%20Licensing%20of%20Digital%20Credit%20Providers%20-%20July%202026.pdf (CBK) | 200, dated "July 14, 2026" in text, matches the CBK press list row 14/07/2026 (https://www.centralbank.go.ke/press/) | Dated and usable, but digital credit sits under `financial-services`, not the chosen niche; reserved for a 5th niche. The text contains an upstream typo ("8,374,102 million loans"); do not quote that sentence |
| https://saccoreview.co.ke/unpacking-sasra-supervision-report-2024-a-sector-in-resilient-expansion/ | 200, dated 2025-10-07 | Trade paper, not on the 6.5 allowlist |
| https://www.gsma.com/newsroom/press-release/mobile-technologies-contributed-240-billion-to-africas-economy-in-2025-as-the-continent-enters-a-new-phase-of-digital-transformation/ (16 June 2026) and World Bank Food and Nutrition Security Update 122 (29 May 2026) | 200 | Continental/global, not Kenya-specific, so they do not fit `country: KE` |

## Implications for the REQ-IDs

- REQ-RES-01 / AC-RES-1 (a published card needs >= 1 official source or >= 2 independent publishers): `microfinance-saccos` (3 SASRA items) and `agriculture` (2 MoALD items) have current official excerpts; `networks-telecommunications` has one official excerpt that is from 2023 (ke-tel-005), so telecom cards rely on >= 2 independent publishers (Business Daily, Capital FM); `health` has no official excerpt (the Ministry of Health page timed out), so health cards need >= 2 independent publishers (Capital FM, The Star, The Standard qualify).
- Freshness (spec 6.5: stale at 12 months, auto-archive at 18): ke-tel-005 (2023-11-19) and ke-agr-004 (2025-02-06) are older than 18 months at retrieval and are kept deliberately as background/negative fixtures for the stale/archive logic; the agent should not draft new cards from them alone.
- The set contains a usable conflict: ke-hlt-001 (Sh11 billion "lost" via fraudulent claims, audit) versus ke-hlt-002 (Sh11.6 billion "rejected" fraudulent claims, Health CS). The pipeline must not merge them into one number; "every number in the claim inside a quote" applies.
- Allowlist `sources/ke.yaml` needs both `capitalfm.co.ke` and `capitalfm.africa` (the SACCO article was served from `capitalfm.africa`), plus `kilimo.go.ke`, `www.sasra.go.ke`, `www.ca.go.ke`, `businessdailyafrica.com`, `standardmedia.co.ke`, `the-star.co.ke`. `nation.africa` returns 403 to a non-browser client, so live fetches from it may fail.
- Quotes contain non-ASCII characters (`’`, `–`); the verbatim checker must compare Unicode-exact after whitespace normalisation only, and must not fold quotes.
- Personal data: no quote names a private individual. Public office-holders appear by surname in their official role (ke-hlt-002 "Duale", Health Cabinet Secretary); no quote names an organisation as wrongdoer except ke-tel-004 (Airtel's own statement about the MTR regime) and ke-hlt-001 (unnamed "private hospitals").
- Card `evidence[]` fields map 1:1: `url`, `publisher`, `source_type`, `published_date`, `retrieved_at`, `quote`.

## Open questions

1. Terms of use: publisher ToS/copyright for storing <= 60-word excerpts was not reviewed (Business Daily pages show a "Renew to keep enjoying premium content" banner although the article text was served without login). Human/legal check before release; likely fair-use quotation but not verified.
2. No `filing` or `ngo` items included; add company annual reports (Safaricom, Airtel Africa) or World Bank Kenya Economic Update if the researcher wants tier diversity. The World Bank KEU landing page fetched but no dated Kenya excerpt was extracted.
3. KNBS is the most important official statistics source and is currently unreachable from this environment (certificate chain). Needs a human decision on adding the intermediate CA or using another route.
4. County-level (CIDP), Kenya Gazette and tenders.go.ke excerpts were not collected (not fetched in this pass).
5. Whether `published_date` may be a month-only value (e.g. CBK "May 2026") is not specified; those sources were skipped.
