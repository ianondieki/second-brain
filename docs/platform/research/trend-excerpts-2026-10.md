# Research excerpts for "This week" technology trends (P22-B, REQ-DEV-02, D-60), 2026-10

Retrieved 2026-10-06. Read-only research; no accounts, credentials or authenticated endpoints; TLS verification never disabled
(proxy as configured, CA bundle `/root/.ccr/ca-bundle.crt`). This note is not committed. The YAML files it describes live in the
session scratchpad only and are handed to the implementer separately (see "Where the files are").

## Question

Which short, dated, public excerpts from official technology publishers (a project's own announcement or release-notes page, a
standards body, a regulator, a platform's own developer announcements) can be saved at build time (no runtime fetch) so a model
can draft "This week" technology trend cards, one fact per quote, each quote checkable verbatim against saved page text? D-60
(DECISIONS-NEEDED.md, owner decision 2026-10-05) says "Technology trends are a research-card type from official publishers,
staff-approved and labelled"; this is the second excerpt list for the research pipeline after `research-excerpts-2026-09.md`
(Kenyan niches).

## Short answer

24 excerpts across 8 topic slugs, all `source_type: official`, all dated 2026-04-01 or later (range 2026-06-17 to 2026-10-05; 14
within 14 days of retrieval, 3 within 15-30 days, 6 within 31-90 days, 1 older than 90 days). Per slug: `languages` 4, `web` 3,
`cloud` 3, `databases` 3, `security` 3, `ai` 3, `kenya-ict` 3, `mobile` 2. Per `publisher_kind`: project 10, vendor 9, regulator 3,
standards 2. 14 publishers on 14 hosts. Every quote was copied from text extracted from the fetched page and checked
programmatically: it occurs exactly once in the whitespace-normalised extracted text and is 12-42 words (limit 60); the
page-stated date string appears in the visible text of the same page; the ISO `published_date` is >= 2026-04-01; and the page
path is allowed by that host's robots.txt for the research User-Agent (checked with a wildcard-aware matcher). The YAML was
re-parsed after writing and every quote re-verified from the parsed values (24 of 24 pass).

## Method

Repeats `research-excerpts-2026-09.md` with these differences noted.

1. robots.txt of every host read first (one `curl -L --compressed` per file, same User-Agent as below). Exception, disclosed:
   `blog.python.org/robots.txt` was read after the two blog.python.org pages had been fetched (the host was discovered from a
   link on python.org). It returns HTTP 404 with an HTML "Not Found" page, i.e. no rules, so it changes nothing; all other used
   hosts were read first.
2. Discovery from each publisher's own index pages (python.org/blogs, blog.rust-lang.org, go.dev/blog, react.dev/blog,
   kubernetes.io/blog, postgresql.org news archive, github.blog/changelog, w3.org/news/2026, ca.go.ke/news, the AWS What's New RSS
   feed, developer.apple.com/news) plus WebSearch for the Google Cloud, MDN, OWASP, CBK, KRA and Safaricom leads. Search summaries
   were never used as quotes or dates.
3. Each content page fetched once on 2026-10-06 with `curl -sL --compressed` (User-Agent
   `Mozilla/5.0 (compatible; BridgeResearchBot/0.1)`, `--cacert /root/.ccr/ca-bundle.crt`). The python.org/blogs index was fetched
   twice (the first attempt lacked `--compressed` and returned undecoded gzip); no content page was fetched twice.
4. HTML to text: scripts, styles, noscript, svg removed; tags stripped; entities unescaped; whitespace collapsed (same recipe as
   the 2026-09 note). The extraction and check scripts and the page copies are in the scratchpad only (page text is third-party
   copyright; only the short quotes are stored).
5. A quote must state a dated fact (a release, a deprecation, an end of life, a rule taking effect, a figure); marketing text was
   not used. Quotes keep curly apostrophes as on the page.
6. `source_type: official` for every row. `publisher_kind`: `project` (a software project's own site), `vendor` (a company's own
   developer announcement or changelog), `standards` (W3C, OWASP Foundation), `regulator` (Communications Authority of Kenya).
7. A page without a stated date was skipped (see "Sources tried and not used").

## Evidence table

Each row: claim = the excerpt exists on the page at this URL with this date; the full quote is in `trend_excerpts.yaml` (same
`id`), read 2026-10-06.

| id | topic slug | publisher | kind | published (page) | URL | topic line |
|---|---|---|---|---|---|---|
| tr-lng-001 | languages | Python Software Foundation | project | 2026-10-01 | https://blog.python.org/2026/10/python-31022-31117/ | Python 3.10 reaches end of life with 3.10.22 (1 Oct 2026) |
| tr-lng-002 | languages | Python Software Foundation | project | 2026-10-02 | https://blog.python.org/2026/10/python-3150-rc3/ | Python 3.15.0rc3 is the final planned release candidate |
| tr-lng-003 | languages | The Go Project | project | 2026-08-19 | https://go.dev/blog/go1.27 | Go 1.27 released with generic methods |
| tr-lng-004 | languages | The Rust Project | project | 2026-10-02 | https://blog.rust-lang.org/2026/10/02/demoting-i686-windows-targets-to-std-only/ | Rust 1.100.0 demotes 32-bit Windows MSVC host tools |
| tr-web-001 | web | React | project | 2026-09-09 | https://react.dev/blog/2026/09/09/react-19-3 | React 19.3 stabilises View Transitions and Fragment Refs |
| tr-web-002 | web | World Wide Web Consortium (W3C) | standards | 2026-08-25 | https://www.w3.org/news/2026/web-authentication-an-api-for-accessing-public-key-credentials-level-3-is-now-a-w3c-recommendation/ | WebAuthn Level 3 becomes a W3C Recommendation (passkeys) |
| tr-web-003 | web | Mozilla (MDN Web Docs) | project | 2026-09-29 | https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Releases/157 | Firefox 157 released (developer release notes) |
| tr-cld-001 | cloud | Kubernetes | project | 2026-08-26 | https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/ | Kubernetes v1.37 release: 67 enhancements |
| tr-cld-002 | cloud | Amazon Web Services | vendor | 2026-10-02 | https://aws.amazon.com/about-aws/whats-new/2026/10/amazon-eks-distro-kubernetes-version-1-37/ | Amazon EKS supports Kubernetes 1.37 |
| tr-cld-003 | cloud | Google Cloud | vendor | 2026-09-25 | https://cloud.google.com/blog/products/storage-data-transfer/storage-intelligence-advisor-and-batch-operations-updates | Cloud Storage Intelligence advisor and batch operations reach GA |
| tr-dat-001 | databases | PostgreSQL Global Development Group | project | 2026-09-24 | https://www.postgresql.org/about/news/postgresql-19-beta-4-released-3386/ | PostgreSQL 19 Beta 4; release candidate and GA expected in October |
| tr-dat-002 | databases | PostgreSQL Global Development Group | project | 2026-10-05 | https://www.postgresql.org/about/news/pgvector-087-released-3392/ | pgvector 0.8.7 fixes a buffer overflow (posted by pgvector on postgresql.org) |
| tr-dat-003 | databases | Amazon Web Services | vendor | 2026-10-02 | https://aws.amazon.com/about-aws/whats-new/2026/10/aurora-dsql-partial-indexes/ | Amazon Aurora DSQL adds partial indexes |
| tr-sec-001 | security | GitHub | vendor | 2026-10-02 | https://github.blog/changelog/2026-10-02-unvalidated-npm-trusted-publishing-configurations-now-expire/ | npm trusted publishing configurations expire after 48 hours unless validated |
| tr-sec-002 | security | The Rust Project | project | 2026-09-21 | https://blog.rust-lang.org/2026/09/21/github-actions-leaking-secrets-when-miri-output-is-cached/ | Miri output cached in GitHub Actions can leak secrets to pull requests |
| tr-sec-003 | security | GitHub | vendor | 2026-10-05 | https://github.blog/changelog/2026-10-05-secret-scanning-adds-detectors-for-lovable-supabase-and-more/ | GitHub secret scanning adds Lovable, Pydantic and Supabase detectors |
| tr-mob-001 | mobile | Apple | vendor | 2026-10-05 | https://developer.apple.com/news/?id=kkphp5qo | Apple: iPhone Duo available 23 Oct 2026; Xcode 27.1 adds support |
| tr-mob-002 | mobile | Apple | vendor | 2026-09-16 | https://developer.apple.com/news/?id=idsft9ai | Apple: alternative App Tracking Transparency prompt in the EU from iOS 27.2 |
| tr-ai-001 | ai | GitHub | vendor | 2026-10-02 | https://github.blog/changelog/2026-10-02-selected-models-in-github-copilot-deprecated/ | GitHub Copilot deprecates selected models (2 Oct 2026) |
| tr-ai-002 | ai | Amazon Web Services | vendor | 2026-09-30 | https://aws.amazon.com/about-aws/whats-new/2026/09/s3-vectors-introduces-metadata-pre-filtering/ | Amazon S3 Vectors adds metadata pre-filtering for RAG and semantic search |
| tr-ai-003 | ai | OWASP Foundation | standards | 2026-09-01 | https://genai.owasp.org/2026/09/01/owasp-genai-security-project-unveils-2026-top-10-for-llm-applications-new-agent-control-standard-and-sponsors-as-community-tops-30000-members/ | OWASP GenAI Security Project releases the 2026 Top 10 for LLM Applications |
| tr-ke-001 | kenya-ict | Communications Authority of Kenya | regulator | 2026-08-06 | https://www.ca.go.ke/ca-resolves-82-cent-ict-consumer-complaints-network-quality-and-fraud-top-grievances | CA: 670 escalated ICT consumer complaints in Apr-Jun 2026, 548 resolved |
| tr-ke-002 | kenya-ict | Communications Authority of Kenya | regulator | 2026-08-13 | https://www.ca.go.ke/ca-clarifies-new-cyber-cafe-license-rules-and-says-no-browsing-history-will-be-required | CA: new licence conditions for cyber cafes and public internet centres, effective 7 Sep 2026 |
| tr-ke-003 | kenya-ict | Communications Authority of Kenya | regulator | 2026-06-17 | https://www.ca.go.ke/increased-adoption-smartphones-and-expansion-mobile-network-infrastructure-drive-surge-kenya | CA sector report: 84.1 million active mobile subscriptions in Q3 FY2025/26 |

Where the page states its date (string checked in the visible text of the fetched page): blog.python.org printed "October 1,
2026" / "October 2, 2026" (also `<time datetime=...>`); go.dev "19 August 2026" under the title; blog.rust-lang.org "Oct. 2, 2026"
and "Sept. 21, 2026"; react.dev "September 9, 2026"; w3.org "Published: 25 August 2026" (also a `2026-08-25T06:44:00+00:00`
timestamp); kubernetes.io "Wednesday, August 26, 2026"; aws.amazon.com "Posted on: Oct 2, 2026" / "Sep 30, 2026"; cloud.google.com
"September 25, 2026" (also `2026-09-25` metadata); postgresql.org "Posted on 2026-09-24" / "2026-10-05"; github.blog "October 2,
2026" / "October 5, 2026" (printed beside "1 minute read"); developer.apple.com "October 5, 2026" / "September 16, 2026";
genai.owasp.org "September 1, 2026" (the press-release dateline inside the post reads "Sept. 2, 2026"; the post's own metadata
is 2026-09-01); ca.go.ke "Submitted by cmstraining on August 6, 2026" (resp. "August 13, 2026", "June 17, 2026"; `cmstraining` is
the CMS account name, not a person, and is not quoted). tr-web-003 is the exception: the MDN page prints no publication date, so
`published_date` is the release date the page states in the quote ("Firefox 157 was released on September 29, 2026").

## robots.txt findings per host (read 2026-10-06, before the first content fetch except where noted)

"Path check" is a wildcard-aware longest-match test (Allow wins ties) of every URL used against the `*` group (no host has a
group for `BridgeResearchBot`).

| host | robots.txt | rules that matter | result for the paths used |
|---|---|---|---|
| blog.python.org | HTTP 404 (HTML "Not Found" page; read after the fetch, see Method 1) | none | allowed (RFC 9309: a missing file allows all) |
| go.dev | 200 | `User-agent: *` / `Allow: /` | allowed |
| blog.rust-lang.org | 200 | `Disallow:` (empty) / `Allow: /` | allowed |
| react.dev | 200 | `Disallow:` (empty) | allowed |
| www.w3.org | 200 (file stamped 2026/07/14) | `*` group disallows WordPress paths such as `/blog/?`, `/blog/*/feed/`, `/*/wp-admin/`; no rule on `/news/2026/` | allowed |
| developer.mozilla.org | 200 | `Disallow: /api/`, `/*/files/`, `/media` | allowed (`/en-US/docs/...`) |
| kubernetes.io | 200 | `Disallow: /legacy/`, `/v1.0/`, `/v1.1/`, `/404/`, `/404.html` | allowed (`/blog/2026/...`) |
| aws.amazon.com | 200 | the group that disallows `/blogs/` and `/*/blogs/` is for `AdsBot-Google` only; the `*` group disallows `/about-aws/whats-new/200`, `/201`, `/2020`-`/2024` (old What's New posts) and `*/blogs/*/tag/` | allowed (`/about-aws/whats-new/2026/...`); a 2024 path was confirmed disallowed by the same matcher |
| cloud.google.com | 200 | `Disallow` list of console, landing, walkthroughs and `terms/looker/...` paths; no rule on `/blog/` (two blog sitemaps are listed) | allowed |
| www.postgresql.org | 200 | `Disallow: /admin/`, `/account/`, `/docs/devel/`, `/list/`, `/search/`, `/message-id/...` | allowed (`/about/news/...`) |
| github.blog | 200 (Yoast block) | `Disallow:` (empty) | allowed |
| genai.owasp.org | 200 | `Disallow: /wp-content/uploads/wpo/wpo-plugins-tables-list.json`; second group `Disallow:` (empty) | allowed |
| developer.apple.com | 200 | `Disallow: /cgi-bin/`, `/click/`, `/documentation/dataformats/`, `/reference/`, `/search/`, `/survey/`, `/temp/`, `/unsubscribe/`, forum paths | allowed (`/news/?id=...`; the query string does not match any rule) |
| www.ca.go.ke | 200 (Drupal default) | `Disallow: /core/`, `/profiles/`, `/admin/`, `/comment/reply/`, `/search/`, `/user/...`, `/media/oembed`; the news slugs sit at the site root | allowed |

Hosts read but not used for an excerpt: developer.android.com (200; disallows asset, image, partner and old release-note paths);
android-developers.googleblog.com (200; `Disallow: /search`, `/share-widget`); nodejs.org (200; `Allow: /dist/latest/`, `Disallow:
/dist/`, `/docs/`; `/en/blog` not covered); www.ietf.org (200; `Disallow: /admin/`, `/search/`); owasp.org (200; `Disallow:
/admin`, `/api/`, `/auth`, `/dashboard`, `/dev`, `/search`); developer.safaricom.co.ke (200; `Disallow:` empty); www.centralbank.go.ke
(200; `Disallow: /wp-admin/`, `/author/`); docs.cloud.google.com (200); www.kra.go.ke (HTTP 404 with an HTML page, so no rules);
mas.owasp.org (404 HTML); blog.google (200; `/search` only). Not readable: www.safaricom.co.ke (HTTP 403, an Incapsula bot-challenge
page instead of robots.txt) and www.ict.go.ke / ict.go.ke (connection failed, curl HTTP 000 through the proxy); neither host was
fetched further.

## Sources tried and not used

| Source | Result (2026-10-06) | Why not used |
|---|---|---|
| https://www.centralbank.go.ke/2026/09/21/draft-national-payment-system-policy-and-national-payment-system-bill-2026/ and its notice PDF `.../uploads/press_releases/873447122_Public Notice - Draft National Payment System Policy and National Payment System Bill, 2026.pdf`, and the Treasury draft policy PDF (`.../wp-content/uploads/2026/09/Draft-National-Payment-System-Policy-2026.pdf`) | 200 | The most relevant Kenyan fintech item (Bill repeals NPS Act Cap. 491A; comments due Friday 9 October 2026). The post and the notice PDF print no publication date (the PDF states only deadlines and forum dates; the policy PDF cover reads "AUGUST 2026"); the date 21/09/2026 appears only in the URL path and in the row of the separate list page https://www.centralbank.go.ke/press/. Skipped per "date stated by the page itself". Same for the draft Virtual Asset Service Providers Regulations notice (list row 18/03/2026, PDF undated). If the owner accepts a listing-page date, these are ready to add |
| https://www.kra.go.ke/news-center/public-notices/2390-implementation-of-the-stock-management-functionality-for-electronic-invoicing (7 Sep 2026), `.../2388-implementation-of-the-etims-...-ifmis-integration` (31 Aug 2026), `.../2395-waiver-of-penalties-and-interest-arising-from-itax-portal-downtime` (17 Sep 2026) | 200 | The pages print a date and a title but no body text (the notice content is not in the HTML); a title alone is not a dated fact. KRA's press-release pages found were revenue and enforcement news, not technology |
| https://android-developers.googleblog.com/2026/09/build-your-way-use-any-ai-agent-in-android-studio.html and three other posts (`.../2026/08/app-broader-memory-limits.html`, `.../2026/09/unlocking-Google-play-subscription-growth.html`, `.../2026/07/google-play-age-signals-api-safer-experiences.html`) | 200 | Blogger pages carry no printed or metadata publication date (only the year/month in the URL); the dates exist only in the RSS feed. Skipped |
| https://developer.android.com/developer-verification | 200 | States "Effective September 30, 2026" and a timeline but no page publication or update date; skipped (an effective date is not a publication date). https://developer.android.com/about/versions/17/release-notes prints "Last updated 2026-10-05 UTC" but its content is a build table, not a trend |
| https://www.safaricom.co.ke (robots and pages) | HTTP 403 bot challenge | Not worked around |
| https://developer.safaricom.co.ke/ | 200 | Marketing landing page, no dated announcements; the Daraja 3.0 launch (reported November 2025) predates the 2026-04-01 floor and was found only via third-party news |
| https://www.ict.go.ke/ | connection failed (HTTP 000) | Failed; not worked around |
| https://www.ietf.org/blog/agentic-ai-standards/ (22 Jan 2026) | 200 | Written by an individual participant ("these are just my opinions"), and before 2026-04-01. https://www.ietf.org/blog/email-service-transition-2026-09/ (11 Sep 2026) is dated and official but an infrastructure change for IETF's own mail, not a trend. Other IETF blog posts found are from 2025 |
| https://nodejs.org/en/blog/release/v26.10.0 (2026-09-22) | 200 | The "Notable Changes" list is commit lines with contributor names (personal data in the quote) and no sentence stating a fact |
| https://kubernetes.io/blog/2026/10/05/scaling-kubernetes-workloads-with-node-swap/ | 200 | Page carries two conflicting metadata dates (2026-09-30 and 2026-10-05); skipped. Also fetched and not used: https://kubernetes.io/blog/2026/07/08/announcing-etcd-3.7/ and .../2026/05/26/reconciling-unfixed-kubernetes-cves/ (both usable, kept in reserve) |
| https://cloud.google.com/blog/products/ai-machine-learning/what-google-cloud-announced-in-ai-this-month | 200 | Rolling monthly page whose metadata says 2025-02-08 and 2026-09-01; ambiguous date, skipped |
| https://www.python.org/downloads/release/python-3148/ | 200 | Dated "Sept. 30, 2026" and usable; not used because the same news (3.14.8, security release) is covered by tr-lng-001 |
| https://owasp.org/blog/ (redirected to owasp.github.io/blog/) | 404 | No owasp.org blog index at that path; the OWASP GenAI project's own post was used instead |
| https://www.ca.go.ke/media-center/press-releases, `/press-releases`, `/Numbering-Management-System`; https://kubernetes.io/blog/2026/08/27/kubernetes-v1-37-release/ | 404 | Guessed URLs that do not exist (the real pages were found from the site's own index) |

## Implications for the REQ-IDs

- REQ-DEV-02 / D-60: all 24 rows are `official` with a page-stated date, so every trend card can cite at least one official
  source; a staff-approved card needs only one row (there is no independent-publisher fallback in this set, which is by
  design: news sites are excluded). Cards should be labelled with the publisher and `published_date`; the topic line is only a
  hint for the model, not copy.
- Reuse of the REQ-RES-01/02 machinery: the row shape is the 2026-09 shape with `topic_slug` instead of `niche`, `country: TECH`
  and one extra field `publisher_kind`. A loader that rejects unknown keys must be told to accept `publisher_kind`; one that
  keys on `niche` must read `topic_slug`. `retrieved_at` is `2026-10-06` for every row.
- Freshness: the 2026-09 stale/archive rule (12 and 18 months) never triggers here, but "This week" implies a much shorter
  window. 14 of 24 rows are within 14 days of retrieval; by the time P22-B ships, rows older than about 30 days (7 now) will no
  longer be "this week". The implementer should either filter by `published_date` against the build date or refresh the file
  (a re-run of this note's method takes roughly a day of research).
- AC-RES-1 style checks (every number in a claim must appear inside a quote): several quotes carry exact figures that a model
  must not restate differently: 67/16/23/27/1 (tr-cld-001), 156 bugfixes and 82 contributors (tr-lng-002), 670/548/122
  (tr-ke-001), 84.1 million, 7.4 per cent, 8.2 percentage points, 157.7 per cent (tr-ke-003), 5x and 48 hours and 10,000
  downloads (tr-ai-002, tr-sec-001, tr-ai-003).
- Personal data: no quote names a private individual. Organisations named: Python, Go, Rust, React, W3C, Firefox, Kubernetes, EKS,
  Amazon (Aurora DSQL, S3 Vectors), GitHub (Copilot, npm, Actions), pgvector, PostgreSQL, Lovable, Pydantic, Supabase, Apple,
  OWASP, Communications Authority of Kenya. `allowlist.yaml` lists an organisation entry for each, plus Google, Microsoft,
  Safaricom and KRA (not named in any quote).
- Quotes contain non-ASCII characters (`’`); the verbatim checker must compare Unicode-exact after whitespace normalisation only,
  as in the 2026-09 note.
- Principle 4 (no logos, organiser name only) is not touched: no logo or image is stored.

## Open questions

1. Terms of use and content licences were not reviewed (D-38 is the owner's open legal question for stored excerpts). One licence
   is visible on a used page: the Python Insider footer reads "CC BY-NC-SA 3.0", i.e. NonCommercial, which may matter for a
   paid product; the other publishers' licences (React, Kubernetes, GitHub, AWS, Apple, Google, W3C, Mozilla, OWASP, PostgreSQL,
   CA) were not checked. Likely fair-use quotation of 12-42 words with attribution, not verified. Human/legal check before release.
2. `official: true` in `allowlist.yaml` means "the publisher is the subject itself" (as the task asked). In `ke.yaml` it means a
   government or regulator source, and `sources.py` uses it to decide what counts as an official source. If the loader is shared
   with the Kenya list, the owner should confirm that a vendor's own announcement counts as official for AC-RES-1 (D-45
   default (a) makes a card that names an organisation need an official source).
3. tr-dat-002 (pgvector) is an announcement by the pgvector project that the PostgreSQL project hosts in its news archive
   ("Posted on 2026-10-05 by pgvector"); the host, and so the allowlist publisher, is the PostgreSQL Global Development Group.
   Drop it if only the project's own authorship should count.
4. tr-web-003 has a release date rather than a publication date (MDN prints none); whether that is acceptable as
   `published_date` is not specified.
5. CBK and KRA dates: whether a date shown on a separate listing page may stand for an undated PDF or post (the CBK National Payment
   System draft, the VASP regulations draft) is not specified; the rule applied here is "no". The comment deadline 9 October 2026
   for the NPS Bill makes that item time-critical for a Kenyan fintech card.
6. `mobile` has only 2 rows and `kenya-ict` has no fintech row; Android (developer verification, Play policy), Safaricom/Daraja,
   ICT Ministry and KRA technology notices could not be added for the reasons above. Whether a "kenya-fintech" slug is wanted
   needs the owner to name a source that prints a date (for example the Kenya Gazette).
7. The slug names are mine (`languages`, `web`, `cloud`, `databases`, `security`, `ai`, `mobile`, `kenya-ict`); they are not read
   from `backend/seed/reference.yaml` and the task card did not fix them. `languages` holds Python, Go and Rust; split it if the
   UI wants a `python` chip.
8. `go.dev`, `www.postgresql.org` and `aws.amazon.com` etc. were allowlisted at the exact host used; if a card's URL could be a
   sibling host (for example `docs.python.org`, `pkg.go.dev`, `docs.aws.amazon.com`), those hosts are not on the list and would
   be refused.
9. Some page content reads as forward-dated relative to my training cut-off (for example Xcode 27.1, Go 1.27, Rust 1.99, React
   19.3, Kubernetes 1.37); all of it was read live on 2026-10-06 and nothing was filled in from memory, but a reviewer should
   expect that a fact is "new" only for a few weeks.

## Where the files are

- `/tmp/claude-0/-home-user/4b8a13b8-adb0-5902-afd2-2542804d507b/scratchpad/p22/trends/trend_excerpts.yaml` (24 rows)
- `/tmp/claude-0/-home-user/4b8a13b8-adb0-5902-afd2-2542804d507b/scratchpad/p22/trends/allowlist.yaml` (14 domains, 20 organisations)
- the page copies, the robots files and the scripts (`scripts/build.py`, `scripts/write_yaml.py`, `scripts/robots_check.py`) are in
  the same directory (`raw/`, `scripts/`); they are not part of the repository.
