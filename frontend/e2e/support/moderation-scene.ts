import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { ownerSql as researchOwnerSql } from "./research-scene";
import { demoTotpSecret, totp } from "./totp";
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
/**
 * A demo staff login. Its codes start after the last one the API accepted for the account (read by the owner), not
 * after the last one this process used: a retry or a rerun runs in a new worker, and the API refuses a code whose
 * window is not later than the last accepted one.
 */
export class DemoStaff extends Person {
  private last = 0;

  override async code(): Promise<string> {
    const stored = Number(
      researchOwnerSql("SELECT coalesce(totp_last_counter, 0) FROM users WHERE email = :'email';", {
        email: this.email,
      }),
    );
    const now = Math.floor(Date.now() / 30_000);
    const counter = Math.max(this.last + 1, stored + 1, now - 1);
    if (counter > now + 1) await new Promise((r) => setTimeout(r, (counter - now - 1) * 30_000 + 1_000));
    this.last = counter;
    return totp(this.secret, { time: counter * 30_000 });
  }
}

export const DEMO_MODERATOR = new DemoStaff(
  "moderator@staff.example",
  "Staff Moderator (demo)",
  demoTotpSecret("moderator@staff.example"),
);
export const DEMO_ADMIN = new DemoStaff(
  "admin@staff.example",
  "Staff Admin (demo)",
  demoTotpSecret("admin@staff.example"),
);

export const P6_TITLE = "Clear loan-fee statements for SACCO members";
export const P6_PROBLEM_TITLE = "SACCO members cannot check loan fees";
export const DEMO_CLAIM_ORG = "County Government of C (fixture)";

/** The demo items a walkthrough run decides: P6 itself (desktop) or the new problem P6 describes (360 px). */
export type DemoItem = "proposal" | "problem";

// Each demo item by title, and only among rows of demo accounts (`users.demo_account`, set by the demo seed and never by
// the application): the reset below can never touch a real person's proposal or problem that shares a title.
const DEMO_SUBJECT: Record<DemoItem, string> = {
  proposal:
    "SELECT p.id FROM proposals p JOIN users u ON u.id = p.owner_id AND u.demo_account WHERE p.title = :'title'",
  problem:
    "SELECT pr.id FROM problems pr JOIN users u ON u.id = pr.created_by AND u.demo_account" +
    " WHERE pr.title = :'title' AND pr.source = 'developer'",
};
const DEMO_TITLE: Record<DemoItem, string> = { proposal: P6_TITLE, problem: P6_PROBLEM_TITLE };

/**
 * The demo seed is there (the owner reads it): both demo staff, County C's claim and, with `item`, that item's case,
 * unresolved. A clear message when it is not.
 */
export function expectDemoQueues(item?: DemoItem): void {
  const found = ownerSql(
    "SELECT (SELECT count(*) FROM users WHERE email IN ('moderator@staff.example', 'admin@staff.example')" +
      " AND staff_role IS NOT NULL) || ',' ||" +
      " (SELECT count(*) FROM org_claims c JOIN organizations o ON o.id = c.org_id WHERE o.legal_name = :'org');",
    { org: DEMO_CLAIM_ORG },
  );
  expect(found, "the demo seed's staff (2) and County C's claim (1): run python -m bridge.seed --demo").toBe("2,1");
  if (!item) return;
  const open = ownerSql(
    `SELECT count(*) FROM moderation_cases WHERE subject_type = :'type' AND subject_id IN (${DEMO_SUBJECT[item]})` +
      " AND status IN ('open', 'held', 'escalated') AND decided_at IS NULL;",
    { type: item, title: DEMO_TITLE[item] },
  );
  expect(open, `one unresolved case of "${DEMO_TITLE[item]}": run python -m bridge.seed --demo`).toBe("1");
}

/** The id of a demo item: exactly one demo account's row with its title, or the test fails here. */
export function demoItemId(item: DemoItem): string {
  const title = DEMO_TITLE[item];
  const ids = ownerSql(`${DEMO_SUBJECT[item]};`, { title }).split("\n").filter(Boolean);
  expect(ids, `exactly one demo ${item} titled "${title}" (run python -m bridge.seed --demo)`).toHaveLength(1);
  return ids[0];
}

/**
 * Puts one demo item back as the seed left it, so the walkthrough can run again (a second project's run, a CI retry,
 * a local rerun): P6 held, or P6's new problem published and clear, and its case open with no decision. Each project
 * resets only the item it decides, so the two runs never touch each other's. Test data only (the demo refuses to seed
 * outside dev and test).
 */
export function reopenDemoItem(item: DemoItem): void {
  const title = DEMO_TITLE[item];
  const id = demoItemId(item);
  // One statement, so one transaction: the item (only while it is still a demo account's row) and its case. The count
  // check runs inside it: anything but exactly one item and one case raises (a text that is not a number cast to int),
  // and the statement's changes roll back, so a mismatch leaves the demo rows as they were.
  const subject =
    item === "proposal"
      ? "UPDATE proposals SET moderation_state = 'held' WHERE id = CAST(:'id' AS uuid)" +
        " AND owner_id IN (SELECT id FROM users WHERE demo_account)"
      : "UPDATE problems SET moderation_state = 'clear', status = 'published', moderator_id = NULL" +
        " WHERE id = CAST(:'id' AS uuid) AND created_by IN (SELECT id FROM users WHERE demo_account)";
  const changed = ownerSql(
    `WITH subject AS (${subject} RETURNING id),` +
      " reopened AS (UPDATE moderation_cases SET status = 'open', decided_by = NULL, decided_at = NULL," +
      " updated_at = now() WHERE subject_type = :'type' AND subject_id IN (SELECT id FROM subject) RETURNING id)," +
      " counts AS (SELECT (SELECT count(*) FROM subject) AS s, (SELECT count(*) FROM reopened) AS r)" +
      " SELECT CASE WHEN s = 1 AND r = 1 THEN '1,1'" +
      " ELSE CAST('reset refused: ' || s || ',' || r AS int)::text END FROM counts;",
    { id, type: item },
  );
  expect(changed, `the demo ${item} "${title}" and its one case, reset`).toBe("1,1");
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
