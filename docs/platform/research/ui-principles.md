# UI and front-end principles: what ten engineers and the HCI canon have published (P25, D-67)

Retrieval date for every source below: 2026-10-08 (UTC). Method: WebFetch (page summarised by a small model, quotes
taken from its output) and, for one page (Deno 1.0), a direct `curl` of the HTML to confirm the quote. Where a fetch
tool paraphrased, the table says "paraphrase". Read-only research; no accounts, no authenticated calls, no repository
edits. House format follows `docs/platform/research/design-skills.md`.

## Question

The owner wants the Bridge portal (Next.js 16 / React 19 / Tailwind 4, 150 KB gz per route per AC-UX-3) to be
something named front-end engineers would recommend. What have Addy Osmani, Lea Verou, Sara Soueidan, Dan Abramov,
Evan You, Kent C. Dodds, Harry Roberts, Rachel Andrew, Paul Irish and Ryan Dahl actually published on building
interfaces, and what do Nielsen's heuristics, WCAG 2.2 AA and the WAI-ARIA Authoring Practices say, that an
implementer can check?

## Short answer

Published, checkable guidance exists for most of the list and converges on: ship little JavaScript and budget it
(Osmani); treat CSS as render-blocking and keep specificity low (Roberts); prefer semantic, outline-based, 3:1 focus
indicators that survive forced colors (Soueidan, WCAG); keep effects for synchronising with external systems and
derive everything else during render (Abramov / React docs); test through accessible roles the way a user does
(Dodds); follow APG key maps for the command palette and calendar. Coverage gaps, stated honestly in the open
questions: no Sara Soueidan page on prefers-reduced-motion was found; Evan You's "approachable" is not in any page
read; Rachel Andrew's container-query writing was not found (her grid and subgrid writing was); Paul Irish's
authored Core Web Vitals pages were not found (CWV pages below are by other authors and are labelled so); Dan
Abramov's "keep client code small" is not stated in the pages read (the React docs carry that claim, not him).

## Evidence

Source IDs (S1..) are used by the checklist. "Para." means the fetch tool paraphrased rather than quoted.

### Addy Osmani

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S1 | Budgets are set per page and device class; he gives 170 KB JS as a mobile example | "Our product page must ship less than 170KB of JavaScript on mobile"; "e.g. < 170KB JS (min/gzip) for mobile and < 1.5MB for desktop"; Tinder: "a main bundle budget of 170KB and a CSS budget of 20KB" checked on each PR (Start Performance Budgeting, 2 Oct 2018) | https://addyosmani.com/blog/performance-budgets/ | 2026-10-08 |
| S2 | Cost of JS is download plus CPU execution (Osmani and Bynens, 25 Jun 2019) | "In 2019, the dominant costs of processing scripts are now download and CPU execution time."; "Download times are critical for low-end networks." | https://v8.dev/blog/cost-of-javascript-2019 | 2026-10-08 |
| S3 | Fetch priority for LCP images (authors incl. Osmani; last updated 2023-11-14) | "You can specify `fetchpriority="high"` to boost the priority of the LCP or other critical images."; values `high`, `low`, `auto` ("The default value, which lets the browser choose") | https://web.dev/articles/fetch-priority | 2026-10-08 |
| S6 | Lazy-load only below the fold; set width and height (authors incl. Osmani; updated 2024-08-13) | "Use `loading=lazy` only for images outside the initial viewport."; "we recommend adding `width` and `height` attributes to all `<img>` tags." | https://web.dev/articles/browser-level-image-lazy-loading | 2026-10-08 |
| S5 | Adaptive loading: signals and principle. Byline is Milica Mihajlija; the article summarises a talk by Osmani and Nate Schloss (updated 2019-12-16) | "A fast core experience for all users (including low-end devices)"; `navigator.connection.saveData` "used to leverage the user's Data Saver preferences"; `effectiveType` "used to fine-tune data transfer to use less bandwidth" | https://web.dev/articles/adaptive-loading-cds-2019 | 2026-10-08 |
| S4 | Save-Data client hint. Not an Osmani byline (Gash, Grigorik, Wagner; updated 2016-02-18); `prefers-reduced-data` is not mentioned | "the `Save-Data` client hint request header"; "check if `navigator.connection.saveData` is equal to `true`" | https://web.dev/articles/optimizing-content-efficiency-save-data | 2026-10-08 |
| S7 | Budget definition and enforcement. Byline Milica Mihajlija (2018-11-05), not Osmani | "A performance budget is a set of limits imposed on metrics that affect site performance."; recommends Lighthouse CI among tools; over budget: optimize, remove, or do not add | https://web.dev/articles/performance-budgets-101 | 2026-10-08 |
| S8 | CAUTION, low trust: images.guide is credited "An eBook by Addy Osmani" but the fetched page carried unrelated betting/gaming links, so do not rely on it | "Avoid lazy-loading images above the fold."; "srcset allows a browser to select the best available image per device." (not used in the checklist) | https://images.guide/ | 2026-10-08 |

### Lea Verou

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S9 | LCH over HSL for perceptual colour (4 Apr 2020; browser-support remarks are dated) | "In LCH, the same numerical change in coordinates produces the same perceptual color difference."; "In HSL, lightness is meaningless."; "We have no access to one third of the colors in most modern monitors." | https://lea.verou.me/blog/2020/04/lch-colors-in-css-what-why-and-how/ | 2026-10-08 |
| S10 | Custom-property defaults and `@property` (15 Oct 2021; Chromium-only then) | Preferred: set `--_color: var(--color, black)` and use `--_color` internally ("my preferred solution"); "Property registration is global" and "fails silently", last registration wins; registering "makes it animatable" | https://lea.verou.me/blog/2021/10/custom-properties-with-defaults/ | 2026-10-08 |
| S11 | Nesting desugars to `:is()` (CSSWG issue comment, 18 Oct 2023) | "We currently desugar every nested rule using `:is()`, even when it's completely redundant."; "`:is()` has a flat specificity equal to the specificity of its argument with the highest specificity"; "`:is()` cannot do pseudo-elements" | https://lists.w3.org/Archives/Public/public-css-archive/2023Oct/0573.html | 2026-10-08 |
| S12 | `:has()` performance concern (CSSWG comment, 29 Nov 2017; historical, before browsers shipped `:has()`) | ":has() is not in the fast selector profile"; "will not be available in regular CSS, just JS." | https://lists.w3.org/Archives/Public/public-css-archive/2017Nov/0563.html | 2026-10-08 |

No Lea Verou blog post on `:has()` or on nesting was found (web search returned only her W3C comments).

### Sara Soueidan

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S13 | Focus indicators (published 13 Aug 2021, updated 27 Aug 2023) | WCAG 2.4.13: "has a contrast ratio of at least 3:1 between the same pixels in the focused and unfocused states"; 1.4.11: indicators "must have a color contrast ratio of at least 3:1 against adjacent colors"; recommends a 2px solid outline; outlines are "retained in forced colors modes (like Windows High Contrast Mode)"; box-shadow and backgrounds are typically overridden there, so pair a `box-shadow` with an `outline`; use `:focus-visible` (para. for most of these) | https://www.sarasoueidan.com/blog/focus-indicators/ | 2026-10-08 |
| S14 | Accessible icon buttons (22 May 2019) | Hide the icon with `aria-hidden` when the button has visible text; `focusable="false"` on the svg (for IE); visually hidden text inside the button is "picked up and used by screen readers"; `aria-label` on the svg and `aria-labelledby` to the svg `<title>` "fail in some browser / screen reader combinations" (para.) | https://www.sarasoueidan.com/blog/accessible-icon-buttons/ | 2026-10-08 |
| S15 | Her 2018 Smashing Conference talk description | "very simple things you can (and should) do in your CSS, markup, and using SVG"; "optimize your product for Windows High Contrast Mode (WHCM)"; "css variables in combination with the HSL color format" | https://smashingconf.com/ny-2018/speakers/sara-soueidan/ | 2026-10-08 |
| S16 | Forced colors in a recent article (18 Aug 2025, revised 19 Aug 2025) | text and background colour changes "will be overridden in forced colors modes like Windows Contrast Themes"; use the "`forced-colors` feature query and system color keywords" | https://www.sarasoueidan.com/blog/css-scrollspy/ | 2026-10-08 |
| S17 | ARIA discipline (6 May 2025, updated 19 Aug 2025) | "Each `::scroll-marker` element is exposed as a `tab` within the tablist."; course principle "ARIA is a promise."; the marker group "takes up only one tab stop on the page." | https://www.sarasoueidan.com/blog/css-carousels-accessibility/ | 2026-10-08 |

Not found on sarasoueidan.com: reduced motion, target size (the blog index lists no such article; the two articles above that
were opened do not mention `prefers-reduced-motion`). Reduced-motion support below comes from other authors (S19).

### Dan Abramov and the React docs

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S20 | Client and server as one program (9 Apr 2025) | "it's a single function that closes over the network by sending the rest of itself forward in time and space." | https://overreacted.io/react-for-two-computers/ | 2026-10-08 |
| S21 | Effects synchronise; honest dependencies (9 Mar 2019) | "useEffect lets you synchronize things outside of the React tree according to our props and state."; "if you specify deps, all values from inside your component that are used by the effect must be there." | https://overreacted.io/a-complete-guide-to-useeffect/ | 2026-10-08 |
| S22 | What `'use client'` is (25 Apr 2025) | "'use client' exports client functions to the server."; "This is why neither `import` executes any code."; "These directives express the network gap within your module system." | https://overreacted.io/what-does-use-client-do/ | 2026-10-08 |
| S23 | RSC emit JSON; composition (16 Apr 2025). The page does not address keeping client code small | "It's important that React Server Components emit JSON rather than HTML"; "all Client Components could be moved to the Server" (his incomplete example) | https://overreacted.io/jsx-over-the-wire/ | 2026-10-08 |
| S24 | Before reaching for memo (23 Feb 2021) | Techniques "move state _down_" and lift content up via `children`; they are "complementary" to `memo`/`useMemo` | https://overreacted.io/before-you-memo/ | 2026-10-08 |
| S25 | React docs (no author credit on the fetched page; not attributed to Abramov) | "If there is no external system involved ... you shouldn't need an Effect."; "calculate it during rendering"; "Use Effects only for code that should run *because* the component was displayed to the user." | https://react.dev/learn/you-might-not-need-an-effect | 2026-10-08 |
| S26 | Server Components and bundle (React docs, no author credit) | "the bundle does not include the expensive libraries needed to render the static content."; "There is no directive for Server Components."; interactivity by composing with a Client Component using `"use client"` | https://react.dev/reference/rsc/server-components | 2026-10-08 |

### Evan You

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S27 | Vue docs (project docs, not signed by Evan You) | "Vue is designed to be flexible and incrementally adoptable."; "we call Vue 'The Progressive Framework'"; lists "Enhancing static HTML without a build step"; Vue 2 support ended 31 Dec 2023. The word "approachable" does not appear | https://vuejs.org/guide/introduction.html | 2026-10-08 |
| S28 | Vue FAQ: small build for progressive enhancement | "if you are using Vue primarily for progressive enhancement without a build step, consider using petite-vue (only 6kb)"; "Lower barrier to entry and excellent documentation translate to lower onboarding and training costs"; "created by Evan You in 2014" | https://vuejs.org/about/faq.html | 2026-10-08 |
| S29 | His site only identifies him as Vue's creator; no design statements | "I am the creator of the JavaScript framework Vue.js" | https://evanyou.me/ | 2026-10-08 |

### Kent C. Dodds and Testing Library

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S30 | Testing Trophy (3 Jun 2021) | levels "End to End, Integration, Unit, Static"; "The more your tests resemble the way your software is used, the more confidence they can give you." | https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications | 2026-10-08 |
| S31 | Implementation details (17 Aug 2020) | "Implementation details are things which users of your code will not typically use, see, or even know about."; false negative: "a test failure, but it was because of a broken test, not broken app code." | https://kentcdodds.com/blog/testing-implementation-details | 2026-10-08 |
| S32 | Query priority (Testing Library docs, maintained by the community, Kent is the creator; the page does not credit him) | "your test should resemble how users interact with your code (component, page, etc.) as much as possible."; order: `getByRole`, `getByLabelText`, `getByPlaceholderText`, `getByText`, `getByDisplayValue`; then `getByAltText`, `getByTitle`; last `getByTestId` | https://testing-library.com/docs/queries/about/#priority | 2026-10-08 |

### Harry Roberts

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S33 | CSS and the critical path (9 Nov 2018) | "CSS is critical to rendering a page"; "your page will only render as quickly as your slowest stylesheet"; "The browser will still download all of the CSS files, but it will only block rendering on files needed to fulfil the current context."; "Any given page will only use a small subset of styles found in app.css."; critical CSS is "not simple" and "test everything yourself" | https://csswizardry.com/2018/11/css-and-network-performance/ | 2026-10-08 |
| S34 | Fonts (19 May 2020; about Google Fonts, our stack is system fonts per spec 07) | "`preconnect`ing `fonts.gstatic.com` is a good idea."; "`font-display: swap;` is a good idea." | https://csswizardry.com/2020/05/the-fastest-google-fonts/ | 2026-10-08 |
| S35 | CSS Guidelines | "keep always try and keep specificity as low as possible at all times"; "avoid using IDs in CSS."; "Only use `!important` proactively, not reactively." | https://cssguidelin.es/ | 2026-10-08 |
| S36 | Head diagnostics (ct.css) | "Your `<head>` is the single biggest render-blocking part of your page." | https://github.com/csswizardry/ct | 2026-10-08 |

ITCSS: the ITCSS/Skillshare post (26 Nov 2018) was fetched but carries no layer description, so ITCSS content is not cited
(https://csswizardry.com/2018/11/itcss-and-skillshare/).

### Rachel Andrew

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S37 | Subgrid, Smashing Magazine, 3 Jul 2018 (a June 2018 draft; "none of its code worked in browsers yet", so support is not established by this source) | "The tracks of our nested grid have no relationship to tracks on the parent."; `subgrid` makes the nested grid use "the number of tracks and track sizing" of the parent (para.) | https://www.smashingmagazine.com/2018/07/css-grid-2 | 2026-10-08 |
| S38 | Her own index of writing: grid and subgrid articles, none on container queries | e.g. "Digging Into The Display Property: Grids All The Way Down" (24 May 2019), "Editorial Design Patterns With CSS Grid and Named Columns" (4 Oct 2019) | https://rachelandrew.co.uk/work/ | 2026-10-08 |
| S39 | Container queries: web.dev lesson, no individual author named, so not attributed to Andrew (updated 2025-08-21) | "You can define a container by using the `container-type` property."; `@container (inline-size > 30em)`; work "independent of the viewport size" | https://web.dev/learn/css/container-queries | 2026-10-08 |

### Paul Irish and Core Web Vitals

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S40 | His gist (body "Updated slightly April 2020") | Title "What forces layout/reflow. The comprehensive list."; "all APIs that synchronously provide layout metrics will trigger forced reflow / layout"; advises batching DOM reads and writes (para.) | https://gist.github.com/paulirish/5d52fb081b3570c81e3a | 2026-10-08 |
| S41 | His site: DevTools audit post (27 Mar 2015) | "Advanced Performance Audits With DevTools"; no Core Web Vitals post on the page | https://www.paulirish.com/ | 2026-10-08 |
| S42 | INP thresholds (web.dev, Wagner and Barry Pollard, not Irish; published 2022-05-06, updated 2025-09-02) | "An INP below or at 200 milliseconds means a page has good responsiveness."; "An INP above 500 milliseconds means a page has poor responsiveness."; judged at "the 75th percentile of page loads recorded in the field" | https://web.dev/articles/inp | 2026-10-08 |
| S43 | Long tasks (web.dev, Wagner and Brendan Kenny, not Irish; updated 2024-12-19) | "Any task that takes longer than 50 milliseconds is a _long task_."; "`scheduler.yield()` is an API specifically designed for yielding to the main thread in the browser." | https://web.dev/articles/optimize-long-tasks | 2026-10-08 |
| S44 | Lighthouse scoring (Chrome docs, no author credit; page last updated 2019-09-19; first table labelled Lighthouse 10) | weights FCP 10%, SI 10%, LCP 25%, TBT 30%, CLS 25%; "90 to 100 (green): Good" | https://developer.chrome.com/docs/lighthouse/performance/performance-scoring | 2026-10-08 |
| S45 | Real-time metrics in DevTools (bylines Rick Viscomi and Addy Osmani, 24 Sep 2024) | "Last week with the release of Chrome 129, we launched a new real-time metrics view in the Performance panel."; Web Vitals extension support ended 7 Jan 2025 | https://developer.chrome.com/blog/web-vitals-extension | 2026-10-08 |

### Ryan Dahl

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S46 | Deno 1.0 (Dahl, Belder, Iwańczuk; 13 May 2020). Verified by curl of the HTML. The exact phrase "secure by default" is not on the page; the substance is | "code is executed in a secure sandbox by default. Scripts cannot access the hard drive, open network connections, or make any other potentially malicious actions without permission."; "Deno is (and always will be) a single executable file."; "Deno supports TypeScript without additional tooling." | https://deno.com/blog/v1 | 2026-10-08 |

### HCI canon

| ID | Claim | Quote | URL | Read |
|---|---|---|---|---|
| S47 | Nielsen's ten heuristics (Jakob Nielsen; first published 24 Apr 1994, last reviewed 30 Jan 2024) | 1 "Visibility of System Status", 2 "Match Between the System and the Real World", 3 "User Control and Freedom", 4 "Consistency and Standards", 5 "Error Prevention", 6 "Recognition Rather than Recall", 7 "Flexibility and Efficiency of Use", 8 "Aesthetic and Minimalist Design", 9 "Help Users Recognize, Diagnose, and Recover from Errors", 10 "Help and Documentation"; e.g. 7: "Shortcuts — hidden from novice users — may speed up the interaction for the expert user"; 9: "Error messages should be expressed in plain language (no error codes), precisely indicate the problem, and constructively suggest a solution." | https://www.nngroup.com/articles/ten-usability-heuristics/ | 2026-10-08 |
| S48 | WCAG 2.2 SC 2.5.8 Target Size (Minimum), AA | "The size of the target for pointer inputs is at least 24 by 24 CSS pixels, except when:" Spacing, Equivalent, Inline, User Agent Control, Essential | https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html | 2026-10-08 |
| S49 | SC 2.4.11 Focus Not Obscured (Minimum), AA | "When a user interface component receives keyboard focus, the component is not entirely hidden due to author-created content." | https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html | 2026-10-08 |
| S50 | SC 2.4.7 Focus Visible, AA | "Any keyboard operable user interface has a mode of operation where the keyboard focus indicator is visible." | https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html | 2026-10-08 |
| S51 | SC 2.4.13 Focus Appearance is Level AAA (not part of AA) | "at least as large as the area of a 2 CSS pixel thick perimeter of the unfocused component"; "contrast ratio of at least 3:1 between the same pixels in the focused and unfocused states" | https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html | 2026-10-08 |
| S52 | SC 1.4.11 Non-text Contrast, AA | "contrast ratio of at least 3:1 against adjacent color(s)" for "Visual information required to identify user interface components and states" | https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html | 2026-10-08 |
| S53 | SC 2.2.2 Pause, Stop, Hide, Level A | "there is a mechanism for the user to pause, stop, or hide it" for moving, blinking or scrolling information that starts automatically and lasts more than five seconds | https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html | 2026-10-08 |
| S54 | SC 2.3.3 Animation from Interactions is Level AAA (not part of AA) | "Motion animation triggered by interaction can be disabled" unless essential | https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html | 2026-10-08 |
| S55 | `prefers-reduced-motion` (web.dev, Thomas Steiner, not Soueidan; updated 2019-03-11) | values `no-preference` and `reduce`; pattern `@media (prefers-reduced-motion: reduce) { button { animation: none; } }` | https://web.dev/articles/prefers-reduced-motion | 2026-10-08 |
| S56 | `forced-colors` (MDN) | values `none` and `active`; in forced colors `color`, `background-color`, `border-color`, `outline-color`, SVG `fill` and `stroke` take browser values; "`box-shadow` is forced to 'none'"; `forced-color-adjust: none` restores author styles | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/forced-colors | 2026-10-08 |
| S57 | APG Combobox pattern (page shows copyright 2026, no status note) | input "has role combobox"; "aria-controls set to a value that refers to the element that serves as the popup"; popup "has role listbox, tree, grid, or dialog"; "aria-activedescendant set to a value that refers to the focused element within the popup"; "When the popup element is visible, aria-expanded is set to true."; Escape "Dismisses the popup if it is visible." | https://www.w3.org/WAI/ARIA/apg/patterns/combobox/ | 2026-10-08 |
| S58 | APG list autocomplete example (keyboard map) | Down Arrow "moves visual focus to the first suggested value"; Up Arrow "moves visual focus to the last suggested value"; Escape "If the listbox is displayed, closes it."; "Alt + Down Arrow: Opens the listbox without moving focus or changing selection."; `aria-selected="true"` on the highlighted option; `aria-autocomplete="list"` | https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/ | 2026-10-08 |
| S59 | APG Grid pattern | roles `grid`, `row`, `columnheader`, `gridcell`; "Only one of the focusable elements contained by the grid is included in the page tab sequence."; the grid "Requires the author to provide code that manages focus movement inside it."; Control + Home "moves focus to the first cell in the first row." | https://www.w3.org/WAI/ARIA/apg/patterns/grid/ | 2026-10-08 |
| S60 | APG Date Picker Dialog (calendar grid) | Up/Down Arrow move to same day previous/next week; Left/Right to previous/next day; Home/End first/last day of week; Page Up/Down previous/next month; Shift + Page Up/Down same month previous/next year; Escape "Closes the dialog and returns focus to the 'Choose Date' button."; roving tabindex, "only one `gridcell` within the grid is in the dialog Tab sequence."; `aria-live="polite"` on the month heading | https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/examples/datepicker-dialog/ | 2026-10-08 |

## Implications for the REQ-IDs

The REQ-IDs were not read for this note (brief limited it to the sources); mappings are by topic and should be confirmed
by the orchestrator against `REQUIREMENTS.md`.

- AC-UX-3 (LCP, 150 KB gz JS, throttled): S1, S2, S7 support a per-route numeric budget enforced on every change; S42/S44
  give the INP and Lighthouse thresholds that sit beside it.
- REQ-UX-05 (system font stack): Roberts's font advice (S34) is about web fonts; with a system stack none of it is needed.
  It is recorded so nobody re-introduces a webfont "because Roberts says preconnect".
- Spec 04 principle 6 / WCAG 2.2 AA: S48, S49, S50, S52 are AA and testable. S51 (2.4.13) and S54 (2.3.3) are AAA, so
  adopting them is a choice above the bar, not a requirement.
- Command palette and calendar (spec 07 and the reminders/scouts screens): S57, S58 (palette), S59, S60 (calendar/grid).
- Test strategy: S30, S32 align with the Playwright plus axe plan and the vitest component tests.

## Checklist for P25

Each item is a check an implementer can run on the Next.js 16 / React 19 / Tailwind 4 portal. Numeric limits that are
not in a source (the 150 KB gz route budget) are the project's own (AC-UX-3).

1. Fail CI when any route's first-load JS exceeds 150 KB gz; report it per route, not as a site total. (S1 per-page budgets, S7 enforce in the build; 150 KB is AC-UX-3.)
2. Keep a separate, smaller CSS budget and check it in the same step as JS. (S1: Tinder "CSS budget of 20KB"; the number to use is the team's choice, not documented here.)
3. Default every component to a React Server Component; add `"use client"` only to leaf components that hold state or handlers, and list every client component in the PR. (S26, S22.)
4. Do not import heavy libraries (date, markdown, chart) into client components when a Server Component can render the result. (S26: "the bundle does not include the expensive libraries needed to render the static content.")
5. Treat download plus execution as the cost: measure main-thread work at Slow 4G / Moto G-class, not only bytes. (S2, S44.)
6. Mark the LCP image `fetchpriority="high"` and never `loading="lazy"`; use `loading="lazy"` only below the initial viewport. (S3, S6.)
7. Give every `<img>` explicit `width` and `height` so no layout shift occurs. (S6.)
8. Honour `navigator.connection.saveData` (and the `Save-Data` request header when seen) by dropping non-essential images and prefetching; keep a fast core experience for everyone. (S4, S5.)
9. Load no render-blocking third-party script in `<head>`; verify the head with ct.css in a local run. (S36.)
10. Split CSS so a route does not wait on styles it does not use, and inline only a small amount of critical CSS if measured to help. (S33.)
11. Keep selector specificity low: no IDs in selectors, no reactive `!important`; with Tailwind this means utility classes and `@layer`, with custom CSS kept flat. (S35.)
12. When writing nested CSS, remember `&` takes the specificity of the highest selector in its parent list, and a nested rule on a pseudo-element needs checking in the target browsers. (S11.)
13. Define design tokens as custom properties and, for component defaults, use a private `--_name: var(--name, default)` pattern; register with `@property` only where animation or typing is needed and names are namespaced, because registration is global and fails silently. (S10.)
14. Pick colours in a perceptually uniform space (OKLCH/LCH) and verify contrast numerically; do not rely on HSL lightness. (S9, S52.)
15. Use `:has()` for parent-state styling only on small subtrees and check INP afterwards; the 2017 performance worry (S12) predates shipped support, so measure rather than assume.
16. Use container queries (`container-type: inline-size`, `@container`) for components placed in more than one width of slot, and `subgrid` to align nested items to a parent grid; media queries stay for page-level layout. (S39, S37; note S37 predates browser support, so confirm support in the browser matrix before use.)
17. Every interactive element shows a `:focus-visible` indicator that is a 2px solid `outline` with at least 3:1 contrast against adjacent colours, and the indicator is not clipped or covered by sticky headers. (S13, S50, S52, S49. The 2px/3:1 shape is AAA 2.4.13 (S51) but is the cheap way to satisfy AA.)
18. Under `@media (forced-colors: active)`, check that focus outlines, borders and icon `fill`/`stroke` survive; use system colour keywords, and never rely on `box-shadow` or background alone for state. (S56, S16, S13.)
19. Icon-only buttons: `aria-hidden` on the svg, `focusable="false"`, and a visually hidden text label or the accessible name on the button; do not name the button only through svg `aria-label` or `<title>`. (S14.)
20. Wrap every non-essential animation in a `prefers-reduced-motion: reduce` override, test with the emulation in Playwright, and give auto-moving content longer than five seconds a pause control. (S55, S53. S54 is AAA.)
21. Every pointer target is at least 24 by 24 CSS pixels, or has the spacing exception; the 360 px `mobile-360` project checks it. (S48.)
22. Command palette: input `role="combobox"` with `aria-expanded`, `aria-controls` to a `role="listbox"` popup, `aria-activedescendant` for the highlighted option, `aria-autocomplete="list"`; Down/Up move to first/last suggestion, Escape closes, Alt+Down opens without moving focus. (S57, S58.)
23. Calendar/date grid: `role="grid"` with a single roving tab stop, arrows move by day and week, Page Up/Down by month, Shift+Page by year, Escape closes and returns focus to the trigger, month heading in `aria-live="polite"`. (S59, S60.)
24. Compute derived values during render, not in `useEffect`; keep effects for syncing with external systems, list every dependency, and put click-caused logic in the event handler. (S25, S21.)
25. Before adding `memo`/`useMemo`, try moving state down into the component that uses it or lifting static content up as `children`. (S24.)
26. Tests query by role first, then label, text, then alt/title, and `getByTestId` only as a last resort; test what is rendered, not state or internals; keep the pyramid weighted towards integration plus Playwright journeys. (S32, S31, S30.)
27. Error messages state the problem in plain language with no codes and suggest a fix; destructive or irreversible actions offer undo or confirmation; each screen shows the system status (saved, sending, failed). (S47 heuristics 1, 3, 5, 9.)
28. Keep expert shortcuts (palette, keyboard) optional so novices are not required to know them, and keep each screen's content to what is needed now. (S47 heuristics 7, 8.)
29. Scripted secure default for any code the portal runs in tooling: grant the minimum permissions (for example when running scripts under Deno or CI); this mirrors Dahl's "without permission" default but is a principle, not a UI check. (S46.)

## Open questions

1. Sara Soueidan on `prefers-reduced-motion` and target size: no page found on her site (the blog index lists none). Is a primary source required, or are web.dev and WCAG enough (the checklist uses these)?
2. Evan You: no page in his own words on "approachable APIs" or progressive enhancement was found; Vue's own docs say "incrementally adoptable" and "The Progressive Framework" but are project docs. A talk transcript or interview (for example Vue.js Live) would be needed for a first-person claim; not read.
3. Rachel Andrew on container queries: not found under her name; the web.dev lesson has no byline. Her subgrid piece is from 2018 and pre-support.
4. Paul Irish: his gist and a 2015 post were found; his Core Web Vitals / INP work (Lighthouse, DevTools) was not located as authored pages. The INP and long-task pages cited are by Wagner, Pollard and Kenny.
5. Dan Abramov: nothing read states "keep client code small"; that claim lives only in the React docs (S26).
6. images.guide returned unrelated promotional links when fetched: possibly compromised or an ad overlay. Do not link it from the portal until checked in a browser.
7. Lighthouse weights (S44) are the table labelled Lighthouse 10 on a page last updated 2019-09-19; confirm the current Lighthouse version's weights before quoting them in a gate.
8. Item 29 is a principle with no UI test; the orchestrator may drop it to keep the checklist to UI items (it is within the 20 to 30 range either way).
9. Next.js 16-specific behaviour (route bundle reporting, image component defaults) was out of scope and is not cited; the researcher for phase 1 versions (`phase1-versions.md`) may cover it.
