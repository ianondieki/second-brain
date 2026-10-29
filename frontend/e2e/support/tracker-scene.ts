import { spawnSync } from "node:child_process";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { waitForSignInLink } from "./mailpit";
import { totp } from "./totp";

/**
 * Both parties of one engagement for the tracker's E2E (REQ-ENG-03), built through the API wherever it has a path,
 * the way the backend's engagement tests build theirs (backend/tests/integration/engagements/api_world.py):
 *
 * - an organisation member signs up (owner + admin of a new organisation) and turns on two-step sign-in;
 * - a developer signs up, turns on two-step sign-in, publishes a proposal and pitches it to that organisation,
 *   which opens a SUBMITTED engagement.
 *
 * Only what no API offers yet is written as the database owner, for test accounts only (every address is under
 * example.com): the developer's D1 and D2 levels (no SMS or identity check in the stack), the organisation's E2
 * verification with the signatory role and the Master Enterprise Terms acceptance (the claim review is REQ-DIR-03),
 * and an old second factor to exercise the step-up.
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner. Without it the tracker specs skip.
 * The API must run with FEATURE_DEALS_ENABLED=true and FEATURE_TIER2_ENABLED=true, and the seed (the mutual NDA).
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

export const PASSWORD = "accent season in nairobi";

const TEST_EMAIL = /^[a-z0-9.+-]+@([a-z0-9-]+\.)*example\.com$/;

export function ownerSql(sql: string, variables: Record<string, string>): string {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  if (variables.email && !TEST_EMAIL.test(variables.email)) throw new Error("test accounts (@example.com) only");
  const args = [OWNER_DATABASE_URL, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"];
  for (const [name, value] of Object.entries(variables)) args.push("-v", `${name}=${value}`);
  const result = spawnSync("psql", args, { input: sql, encoding: "utf-8", timeout: 15_000 });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

/**
 * Waits until the caller's buttons work: the tracker's actions region says it has hydrated. The server's HTML shows
 * the buttons first, and a press before hydration does nothing (seen under two workers).
 */
export async function actionsReady(page: Page) {
  await expect(page.locator("[data-actions][data-hydrated='true']")).toBeVisible({ timeout: 20_000 });
}

export function tag() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

export async function post<T>(request: APIRequestContext, path: string, data: unknown, status = 200): Promise<T> {
  const response = await request.post(path, { headers: { "X-CSRF-Token": await csrf(request) }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return (await response.json()) as T;
}

/** A test account with an authenticator: codes are computed from its key, never reused (the API refuses replays). */
export class Person {
  private lastCounter = 0;
  constructor(
    readonly email: string,
    readonly name: string,
    readonly secret: string,
  ) {}

  /**
   * A code the API accepts now: in the current window or the next, later than the last used. Never the window
   * before: the API accepts that one only until the current window ends, so a code computed just before a boundary
   * and checked just after it was refused (a walkthrough CI run, P16-E3). The current window stays accepted for the
   * whole next one, as the demo seed chooses (`bridge/seed/demo/runtime.py` `next_totp_code`).
   */
  async code(): Promise<string> {
    const now = Math.floor(Date.now() / 30_000);
    const counter = Math.max(this.lastCounter + 1, now);
    if (counter > now + 1) await new Promise((r) => setTimeout(r, (counter - now - 1) * 30_000 + 1_000));
    this.lastCounter = counter;
    return totp(this.secret, { time: counter * 30_000 });
  }

  /** Makes this person's sessions' second factor 13 hours old, so the next signature asks for a fresh code. */
  staleSecondFactor(): void {
    ownerSql(
      "UPDATE sessions SET mfa_verified_at = now() - interval '13 hours'" +
        " WHERE user_id = (SELECT id FROM users WHERE email = :'email') AND mfa_verified_at IS NOT NULL;",
      { email: this.email },
    );
  }
}

/** Signs up on `request` (a page's request context, so the page shares the session) and opens the emailed link. */
export async function signUp(request: APIRequestContext, body: Record<string, unknown>): Promise<void> {
  const signup = await request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf(request) },
    data: { password: PASSWORD, accept_terms: true, ...body },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const link = await waitForSignInLink(request, body.email as string);
  const token = new URL(link).hash.replace(/^#token=/, "");
  await post(request, "/api/auth/magic-link/consume", { token });
}

export async function turnOnTotp(request: APIRequestContext, email: string, name: string): Promise<Person> {
  const { secret } = await post<{ secret: string }>(request, "/api/auth/totp/enrol", { password: PASSWORD });
  const person = new Person(email, name, secret);
  await post(request, "/api/auth/totp/confirm", { code: await person.code() });
  return person;
}

export interface OrgSide {
  person: Person;
  orgId: string;
  orgName: string;
}

/**
 * A new E2 organisation whose first member (owner, admin and signatory, Master Enterprise Terms accepted) is signed
 * in on `request` with two-step sign-in on. `orgName` names it (the design screenshots); by default a unique name.
 */
export async function signUpOrg(request: APIRequestContext, { orgName: named }: { orgName?: string } = {}): Promise<OrgSide> {
  const id = tag();
  const domain = `buyer-${id}.example.com`;
  const email = `rita-${id}@${domain}`;
  const name = "Rita Wanjiru";
  const orgName = named ?? `Maziwa Buyers ${id} Limited`;
  await signUp(request, { email, display_name: name, side: "org", org: { legal_name: orgName, kind: "company" } });
  const person = await turnOnTotp(request, email, name);
  const me = (await (await request.get("/api/auth/me")).json()) as { memberships: Array<{ org_id: string; org_name: string }> };
  const orgId = me.memberships.find((m) => m.org_name === orgName)?.org_id;
  expect(orgId, "the new organisation").toBeTruthy();
  ownerSql(
    "UPDATE organizations SET verification = 'e2', verified_domain = :'domain', e2_verified_at = now()" +
      " WHERE id = CAST(:'org' AS uuid);" +
      " UPDATE memberships SET roles = '{owner,admin,signatory}' WHERE org_id = CAST(:'org' AS uuid)" +
      " AND user_id = (SELECT id FROM users WHERE email = :'email');" +
      " INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)" +
      " SELECT gen_random_uuid(), CAST(:'org' AS uuid), u.id, t.id, t.sha256 FROM users u, legal_templates t" +
      " WHERE u.email = :'email' AND t.id = app_current_legal_template('master_enterprise_terms');",
    { domain, org: orgId!, email },
  );
  return { person, orgId: orgId!, orgName };
}

export interface DevSide {
  person: Person;
  title: string;
  engagementId: string;
  /** The developer's display name (what they and, once contact is agreed, the organisation see). */
  name: string;
  /** The published version's pseudonymous handle (what the organisation sees until then). */
  handle: string;
}

/**
 * A developer signed in on `request`, D1 and D2, two-step sign-in on, with one published proposal pitched to
 * `orgId`: the engagement it opened (SUBMITTED). `title` names the proposal (the design screenshots); by default a
 * unique title.
 */
export async function pitchFromDeveloper(
  request: APIRequestContext,
  orgId: string,
  { title: named }: { title?: string } = {},
): Promise<DevSide> {
  const id = tag();
  const email = `dev-${id}@example.com`;
  const name = "Achieng Otieno";
  await signUp(request, { email, display_name: name, side: "developer" });
  const person = await turnOnTotp(request, email, name);
  ownerSql(
    "UPDATE developer_profiles SET verification_level = 'd2', updated_at = now()" +
      " WHERE user_id = (SELECT id FROM users WHERE email = :'email');",
    { email },
  );
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
    id: string;
    children?: Array<{ id: string }>;
  }>;
  const niche = niches.find((n) => n.children?.length)?.children?.[0]?.id ?? niches[0].id;
  const title = named ?? `Maziwa baridi ${id}`;
  const draft = await post<{ id: string }>(
    request,
    "/api/me/proposals",
    {
      teaser: {
        title,
        niche_id: niche,
        county_code: "KE-47",
        maturity: "prototype",
        ask: "pilot",
        problem_statement: "Milk spoils between the evening milking and the morning collection.",
        impact_claims: "Cuts spoilage for 40 farms.",
        summary: "Shared solar chillers booked by SMS, paid per litre.",
      },
      confidential: {
        approach: "Solar chillers with a shared booking queue and per-litre billing.",
        architecture: "USSD front end, a queue service and a meter per chiller.",
        pricing: "KES 2 per litre, first month free.",
        links: ["https://example.com/demo"],
      },
      new_problem: { title: `${title}: milk spoils`, statement: "Small dairy co-ops lose a fifth of the evening milk." },
    },
    201,
  );
  const attestations = (await (await request.get("/api/proposals/attestations")).json()) as { version: string };
  await post(request, `/api/me/proposals/${draft.id}/publish`, {
    attestations: { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true },
    attestation_text_version: attestations.version,
  });
  await post(request, `/api/me/proposals/${draft.id}/tags`, { org_ids: [orgId] }, 201);
  const list = (await (await request.get("/api/me/engagements")).json()) as {
    items: Array<{ id: string; proposal_id: string; state: string }>;
  };
  const engagement = list.items.find((e) => e.proposal_id === draft.id);
  expect(engagement?.state, "the pitch opened an engagement").toBe("SUBMITTED");
  const teaser = (await (await request.get(`/api/proposals/${draft.id}`)).json()) as { owner_handle: string };
  return { person, title, engagementId: engagement!.id, name, handle: teaser.owner_handle };
}
