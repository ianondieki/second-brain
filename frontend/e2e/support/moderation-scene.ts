import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { demoTotpSecret } from "./totp";
import { ownerSql, Person, post, signUp, tag } from "./tracker-scene";

/**
 * The moderation and claims screens' E2E state (REQ-MOD-01, REQ-DIR-03 queue; M2 walkthrough step 6).
 *
 * - The demo seed (`python -m bridge.seed --demo`, run by CI before Playwright; P15-B `bridge/seed/demo/queues.py`):
 *   the staff moderator `moderator@staff.example`, the staff admin `admin@staff.example`, Amina's held proposal P6
 *   and its new problem's open case, and County Government of C (fixture)'s E2 claim awaiting review. Demo logins
 *   share one public password and a TOTP key derived from the address (`bridge/seed/demo/data.py`), dev and test only.
 *   A demo case can be decided once: run the walkthrough on a freshly seeded demo.
 * - Its own scene, repeatable: a developer (D1 set by the database owner, as the other scenes do) publishes a proposal
 *   whose problem statement speaks negatively of a listed organisation, so the rules pre-screen holds it; staff are
 *   made with `newStaffAdmin` (research-scene).
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner.
 */

export const DEMO_PASSWORD = "bridge-demo-2026";
export const DEMO_MODERATOR = new Person(
  "moderator@staff.example",
  "Staff Moderator (demo)",
  demoTotpSecret("moderator@staff.example"),
);
export const DEMO_ADMIN = new Person(
  "admin@staff.example",
  "Staff Admin (demo)",
  demoTotpSecret("admin@staff.example"),
);

export const P6_TITLE = "Clear loan-fee statements for SACCO members";
export const P6_PROBLEM_TITLE = "SACCO members cannot check loan fees";
export const DEMO_CLAIM_ORG = "County Government of C (fixture)";

/** The demo's staff and moderation cases are there (the owner reads them): a clear message when the seed is missing. */
export function expectDemoQueues(): void {
  const found = ownerSql(
    "SELECT (SELECT count(*) FROM users WHERE email IN ('moderator@staff.example', 'admin@staff.example')" +
      " AND staff_role IS NOT NULL) || ',' ||" +
      " (SELECT count(*) FROM moderation_cases m JOIN proposals p ON m.subject_type = 'proposal' AND p.id = m.subject_id" +
      " WHERE p.title = :'title') || ',' ||" +
      " (SELECT count(*) FROM org_claims c JOIN organizations o ON o.id = c.org_id WHERE o.legal_name = :'org');",
    { title: P6_TITLE, org: DEMO_CLAIM_ORG },
  );
  expect(
    found,
    "the demo seed's staff (2), P6's case (1) and County C's claim (1): run python -m bridge.seed --demo",
  ).toBe("2,1,1");
}

/** A proposal's moderation case id (the owner reads it), to open the case page directly. */
export function caseOfProposal(title: string): string {
  const id = ownerSql(
    "SELECT m.id FROM moderation_cases m JOIN proposals p ON m.subject_type = 'proposal' AND p.id = m.subject_id" +
      " WHERE p.title = :'title' ORDER BY m.created_at LIMIT 1;",
    { title },
  );
  expect(id, `the case of "${title}"`).toMatch(/^[0-9a-f-]{36}$/);
  return id;
}

/** Signs `person` in through the login and second-factor screens, with `password`. */
export async function signInThroughScreens(page: Page, person: Person, password: string): Promise<void> {
  const step = { timeout: 20_000 };
  await page.goto("/login");
  await page.locator('form[data-hydrated="true"]').first().waitFor(step);
  await page.getByLabel("Email address").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/, step);
  await page.locator('form[data-hydrated="true"]').first().waitFor(step);
  await page.getByLabel("6-digit code").fill(await person.code());
  await page.getByRole("button", { name: "Continue" }).click();
}

export interface Teaser {
  title: string;
  problem_statement: string;
  impact_claims: string;
  summary: string;
}

export interface Author {
  context: BrowserContext;
  request: APIRequestContext;
  proposalId: string;
  teaser: Teaser;
}

async function nicheId(request: APIRequestContext): Promise<string> {
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
    id: string;
    children?: Array<{ id: string }>;
  }>;
  return niches.find((n) => n.children?.length)?.children?.[0]?.id ?? niches[0].id;
}

async function publish(request: APIRequestContext, proposalId: string) {
  const attestations = (await (await request.get("/api/proposals/attestations")).json()) as { version: string };
  return post<{ moderation: { state: string } }>(request, `/api/me/proposals/${proposalId}/publish`, {
    attestations: { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true },
    attestation_text_version: attestations.version,
  });
}

/**
 * A developer in a browser context of their own who publishes `teaser`; the context stays open so the author can
 * publish a new version later. Close `context` at the end.
 */
export async function publishAs(browser: Browser, baseURL: string, teaser: Teaser): Promise<Author> {
  const context = await browser.newContext({ baseURL });
  const request = context.request;
  const email = `author-${tag()}@example.com`;
  await signUp(request, { email, display_name: "Achieng Otieno", side: "developer" });
  ownerSql(
    "UPDATE developer_profiles SET verification_level = 'd1', updated_at = now()" +
      " WHERE verification_level = 'd0' AND user_id = (SELECT id FROM users WHERE email = :'email');",
    { email },
  );
  const draft = await post<{ id: string }>(
    request,
    "/api/me/proposals",
    {
      teaser: { ...teaser, niche_id: await nicheId(request), county_code: "KE-47", maturity: "mvp", ask: "pilot" },
      confidential: { approach: "A statement service over a read-only copy of the ledger." },
      new_problem: {
        title: `${teaser.title}: unclear charges`,
        statement: "People cannot tell why each charge on their statement was made.",
      },
    },
    201,
  );
  await publish(request, draft.id);
  return { context, request, proposalId: draft.id, teaser };
}

/** The author saves a changed teaser and publishes it as a new version (it joins the open case). */
export async function publishNewVersion(author: Author, teaser: Teaser): Promise<void> {
  const response = await author.request.patch(`/api/me/proposals/${author.proposalId}`, {
    headers: { "X-CSRF-Token": await csrfOf(author.request) },
    data: { teaser },
  });
  expect(response.status(), await response.text()).toBe(200);
  await publish(author.request, author.proposalId);
  author.teaser = teaser;
}

async function csrfOf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

/** Whether a signed-in person on `request` can read the proposal's public teaser (404 while held or rejected). */
export async function teaserStatus(request: APIRequestContext, proposalId: string): Promise<number> {
  return (await request.get(`/api/proposals/${proposalId}`)).status();
}

/** A held teaser: its problem statement speaks negatively of a listed organisation (the rules pre-screen). */
export function negativeTeaser(): Teaser {
  const id = tag();
  return {
    title: `Plain airtime statements, case ${id}`,
    problem_statement: "Customers say Safaricom PLC overcharges them on bundles and cannot explain the charges.",
    impact_claims: "Aims to cut billing disputes at shop counters.",
    summary: "A statement that lists each airtime charge with the bundle rule that set it.",
  };
}

/** A teaser the pre-screen holds as a security weakness: it can never be approved, only rejected. */
export function vulnerabilityTeaser(): Teaser {
  const id = tag();
  return {
    title: `Wallet login check, case ${id}`,
    problem_statement: "We found an authentication bypass in a mobile wallet login that lets anyone in.",
    impact_claims: "Aims to show the weakness so it is fixed.",
    summary: "A short write-up of the login flaw and how to reproduce it.",
  };
}
