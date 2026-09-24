## 7. UX & information architecture

1. **Navigation:** ≤5 items per portal (bottom tabs on mobile, left rail ≥1024 px). Top bar: portal switcher (only if the user belongs to both), bell, avatar menu (Profile, Plan & billing, Notification settings, Language, Help, Sign out). Admin is a separate console.
   - **Developer:** Home (Needs-you list, health chips, 3 trending problems, reminder summary) · Discover (Trending Problems with sources and "Why" chips, Trending Projects beside their problems, Opportunity Gap, niche/county filter, "Start a proposal from this problem") · My Ideas (Draft/Published/Archived, editor, Pitch to company, certificate, versions, Who has seen this) · Engagements (grouped by proposal → one row per org; tabs Tracker · Documents · Messages · History) · Companies (directory by niche). "+ New proposal" is a button, not a nav item.
   - **Enterprise (4 items):** Inbox (Tagged us · Scout matches with "why matched", Configure scout: form + Preview + pause + 👍/👎 · Browse repo) · Engagements (board/list by stage, "Needs us"/"Overdue", tracker + Internal notes) · Problems (Problem Briefs) · Team (members, roles, default assignee per niche, escalation contact, verification status).
2. **One primary action per screen; "Whose turn" banner on every tracker; ≤2 chips per card** (pursuit chip, e.g. "Pursue · Strong fit", combining the pursuit recommendation and fit label, + one Why chip; the rest on expand or the detail page).
3. **Onboarding ≤3 steps, skippable after step 1.** Developer: phone/email OTP + language → liked niches (3–5) + county → optional GitHub connect. Enterprise: work-email OTP → org details + BRS/KRA (queued; banner "Verification in progress – usually 2 business days. You can set up your Scout Agent now.") → invite team. Orgs below E2 cannot see Tier 2 or receive proposals.
4. **Empty states**: one sentence + one action, e.g. Inbox (org): "No proposals yet. Set up your Scout Agent so we can bring relevant ideas to you." → **Set up Scout Agent** (every org plan has a scout). Tagged E0 org: the `docs/spec/06-feature-modules.md#62-company-directory-by-niche-claimed-and-unclaimed` held-tag sentence → **Tag another company**.
5. **Mobile-first, low bandwidth:** design at 360×640; SSR; ≤150 KB JS gzipped per route; LCP ≤2.5 s on Slow 4G / Moto G-class from Nairobi; one system font stack; image-free tracker; Data-saver toggle; service worker caching last-seen trackers for offline read-only (Release 2).
6. **Accessibility WCAG 2.2 AA:** stepper as `<ol>` with `aria-current="step"`; status = icon + text + colour; touch targets ≥44 px; focus never under sticky bars; OTP pasteable; contrast ≥4.5:1; reduced motion respected; axe zero serious/critical; Lighthouse accessibility ≥90.
7. **i18n:** ICU MessageFormat in `locales/en.json` and `locales/sw.json` with identical keys (`next-intl`); Release 1 ships English with complete keys, `sw.json` goes live after native-speaker review at G5; no string concatenation; 30% expansion room; store UTC, display Africa/Nairobi; `KES 1,250,000`; phones E.164.

| AC | Criterion |
|---|---|
| AC-UX-1 | Each portal's nav renders ≤5 items at 360 px and 1280 px; enterprise onboarding has ≤3 steps; no horizontal scroll on any core page; cards show ≤2 chips (snapshot). |
| AC-UX-2 | Every core screen has ≤1 primary button (Playwright assertion on `[data-primary]` count). |
| AC-UX-3 | Lighthouse (throttled Slow 4G, Moto G profile) reports LCP ≤2.5 s and JS ≤150 KB gz on Home, Discover, tracker. |
| AC-UX-4 | axe-core: zero serious/critical violations on all core flows in both locales. |
| AC-UX-5 | Every empty state has exactly one sentence and one action (snapshot test). |
