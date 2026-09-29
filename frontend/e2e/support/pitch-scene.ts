import { spawnSync } from "node:child_process";

import { expect, type APIRequestContext, type Browser } from "@playwright/test";

import { waitForSignInLink } from "./mailpit";
import { totp } from "./totp";

/**
 * The E2E state of "Pitch to companies" and "Who has seen this" (REQ-PROP-03, REQ-PROV-03), built the way the backend's
 * integration scene does (backend/tests/integration/proposals/pitch_helpers.py, tier2_scene.py): through the API
 * wherever the API has a path (signups, publishing, the NDA, the marked Tier-2 page), and as the database owner only
 * for what no API offers yet, for test accounts only (every address is under example.com): the developer's D1 level
 * (the SMS code never leaves the API process), an organisation's E2 verification with its verified domain, the
 * signatory role and its acceptance of the current Master Enterprise Terms (the claim review is REQ-DIR-03).
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner. Without it the specs that need this
 * state skip. The API must run with FEATURE_TIER2_ENABLED=true for the view step.
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

export const PASSWORD = "jacaranda season in nairobi";

const TEST_DOMAIN = /^[a-z0-9-]+\.example\.com$/;

/** SQL as the database owner; values travel as psql variables (quoted by psql, never spliced into the SQL text). */
function ownerSql(sql: string, variables: Record<string, string> = {}): string {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  const args = [OWNER_DATABASE_URL, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"];
  for (const [name, value] of Object.entries(variables)) args.push("-v", `${name}=${value}`);
  const result = spawnSync("psql", args, { input: sql, encoding: "utf-8", timeout: 15_000 });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

export function runTag() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

export async function apiPost<T>(request: APIRequestContext, path: string, data: unknown, status = 200): Promise<T> {
  const response = await request.post(path, { headers: { "X-CSRF-Token": await csrf(request) }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return (await response.json()) as T;
}

async function signUp(request: APIRequestContext, body: Record<string, unknown>): Promise<void> {
  const signup = await request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf(request) },
    data: { password: PASSWORD, accept_terms: true, ...body },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const link = await waitForSignInLink(request, body.email as string);
  const token = new URL(link).hash.replace(/^#token=/, "");
  await apiPost(request, "/api/auth/magic-link/consume", { token });
}

export interface Idea {
  id: string;
  title: string;
}

/** A draft and its publication (the developer on `request` must be D1): one registered version. */
export async function publishIdea(request: APIRequestContext, title: string): Promise<Idea> {
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
    id: string;
    children?: Array<{ id: string }>;
  }>;
  const niche = niches.find((n) => n.children?.length)?.children?.[0]?.id ?? niches[0].id;
  const draft = await apiPost<{ id: string }>(
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
        summary: "Shared solar chillers booked by SMS, paid per litre.",
      },
      confidential: { approach: "Solar chillers with a shared booking queue and per-litre billing." },
      new_problem: { title: `${title}: milk spoils`, statement: "Small dairy co-ops lose a fifth of the evening milk." },
    },
    201,
  );
  const attestations = (await (await request.get("/api/proposals/attestations")).json()) as { version: string };
  await apiPost(request, `/api/me/proposals/${draft.id}/publish`, {
    attestations: { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true },
    attestation_text_version: attestations.version,
  });
  return { id: draft.id, title };
}

/** A draft that is never published. */
export async function draftIdea(request: APIRequestContext, title: string): Promise<Idea> {
  const draft = await apiPost<{ id: string }>(request, "/api/me/proposals", { teaser: { title } }, 201);
  return { id: draft.id, title };
}

export interface Listed {
  id: string;
  name: string;
}

/** An unclaimed (E0) organisation of the seeded directory that this developer has no open pitch with. */
export function listedOrg(developerEmail: string): Listed {
  const row = ownerSql(
    "SELECT o.id || '|' || o.legal_name FROM organizations o WHERE o.verification = 'unclaimed'" +
      " AND o.delisted_at IS NULL AND o.suspended_at IS NULL AND NOT EXISTS (SELECT 1 FROM tags t JOIN users u" +
      " ON u.id = t.developer_id WHERE t.org_id = o.id AND u.email = :'email' AND t.closed_at IS NULL)" +
      " ORDER BY random() LIMIT 1;",
    { email: developerEmail },
  );
  const [id, ...name] = row.split("|");
  expect(id, "a listed unclaimed organisation").toBeTruthy();
  return { id, name: name.join("|") };
}

export interface OrgMember {
  email: string;
  name: string;
  orgName: string;
  orgId: string;
  request: APIRequestContext;
  close: () => Promise<void>;
}

/**
 * A new E2 organisation and its first member (owner, admin and signatory with the Master Enterprise Terms accepted),
 * signed in with two-step sign-in on and fresh, in a browser context of its own.
 */
export async function e2OrgMember(browser: Browser, baseURL: string): Promise<OrgMember> {
  const context = await browser.newContext({ baseURL });
  const request = context.request;
  const id = runTag();
  const domain = `buyer-${id}.example.com`;
  if (!TEST_DOMAIN.test(domain)) throw new Error("test organisations only");
  const email = `rita-${id}@${domain}`;
  const name = "Rita Wanjiru";
  const orgName = `Buyer ${id} Limited`;
  await signUp(request, { email, display_name: name, side: "org", org: { legal_name: orgName, kind: "company" } });
  const { secret } = await apiPost<{ secret: string }>(request, "/api/auth/totp/enrol", { password: PASSWORD });
  await apiPost(request, "/api/auth/totp/confirm", { code: totp(secret) });
  const me = (await (await request.get("/api/auth/me")).json()) as {
    memberships: Array<{ org_id: string; org_name: string }>;
  };
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
  return { email, name, orgName, orgId: orgId!, request, close: () => context.close() };
}

/** The member accepts the Evaluation NDA for the proposal and opens its marked full details: one logged view. */
export async function viewFullDetails(member: OrgMember, proposalId: string): Promise<void> {
  const base = `/api/orgs/${member.orgId}/proposals/${proposalId}`;
  const nda = (await (await member.request.get(`${base}/nda`)).json()) as {
    template_id: string;
    sha256: string;
    logging_notice: { version: string };
  };
  const accepted = await member.request.post(`${base}/nda`, {
    headers: { "X-CSRF-Token": await csrf(member.request) },
    data: { template_id: nda.template_id, sha256: nda.sha256, logging_notice_version: nda.logging_notice.version },
  });
  expect(accepted.status(), await accepted.text()).toBeLessThan(300);
  const page = await member.request.get(`${base}/tier2`);
  expect(page.status(), await page.text()).toBe(200);
}
