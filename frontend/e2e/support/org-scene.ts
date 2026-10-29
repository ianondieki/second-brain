import { spawnSync } from "node:child_process";

import { expect, type APIRequestContext, type Browser } from "@playwright/test";

import { waitForSignInLink } from "./mailpit";
import { totp } from "./totp";

/**
 * The organisation side's E2E state (REQ-PROP-03 Inbox, REQ-REPO-01 NDA and Tier 2), built the way the backend's
 * integration scene does (backend/tests/integration/proposals/tier2_scene.py, pitch_helpers.py), through the API
 * wherever the API has a path:
 *
 * - an organisation member signs up (owner + admin of a new organisation), opens the emailed link and turns on
 *   two-step sign-in (confirming the code marks the session's second factor as fresh);
 * - a developer signs up in their own browser context, writes and publishes a proposal, and pitches it to the
 *   organisation (an E2 organisation gets a delivered tag and, under the default policy, a Tier-2 grant; an E1 one a
 *   held tag).
 *
 * What no API offers yet goes through the database owner, for test accounts only (every address is under
 * example.com). Writes: the developer's D1 level (the SMS code never leaves the API process), the organisation's
 * verification level with its verified domain (the claim review is REQ-DIR-03), the member's roles (signatory for E2;
 * viewer for the role refusal) and the signatory's acceptance of the current Master Enterprise Terms (no acceptance
 * screen yet). Reads: a listed E0 organisation of the seeded directory to pitch elsewhere.
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner (for example
 * postgresql://bridge_owner:…@127.0.0.1:5432/bridge). Without it the specs that need this state skip. The API must
 * run with FEATURE_TIER2_ENABLED=true for the Tier-2 steps.
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

export const PASSWORD = "accent season in nairobi";

const TEST_DOMAIN = /^[a-z0-9-]+\.example\.com$/;

/** Runs SQL as the database owner; values travel as psql variables (quoted by psql, never spliced into the SQL). */
function ownerSql(sql: string, variables: Record<string, string>): string {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  const args = [OWNER_DATABASE_URL, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"];
  for (const [name, value] of Object.entries(variables)) args.push("-v", `${name}=${value}`);
  const result = spawnSync("psql", args, { input: sql, encoding: "utf-8", timeout: 15_000 });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

function tag() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** A CSRF token for this request context (the double-submit cookie is set on the same context). */
async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function post<T>(request: APIRequestContext, path: string, data: unknown, status = 200): Promise<T> {
  const response = await request.post(path, { headers: { "X-CSRF-Token": await csrf(request) }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return (await response.json()) as T;
}

/** Signs up through the API and signs this request context in with the emailed link's token. */
async function signUp(request: APIRequestContext, body: Record<string, unknown>): Promise<void> {
  const signup = await request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf(request) },
    data: { password: PASSWORD, accept_terms: true, ...body },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const link = await waitForSignInLink(request, body.email as string);
  const token = new URL(link).hash.replace(/^#token=/, "");
  await post(request, "/api/auth/magic-link/consume", { token });
}

export interface OrgMember {
  email: string;
  name: string;
  orgName: string;
  orgId: string;
  domain: string;
  /** The authenticator key, for later codes. */
  secret: string;
}

/**
 * A new organisation and its first member (owner + admin), signed in on `request` (use `page.request`, so the page
 * shares the session) with two-step sign-in on and the second factor fresh.
 */
export async function signUpOrgMember(request: APIRequestContext, label = "Buyer"): Promise<OrgMember> {
  const id = tag();
  const domain = `buyer-${id}.example.com`;
  const email = `rita-${id}@${domain}`;
  const name = "Rita Wanjiru";
  const orgName = `${label} ${id} Limited`;
  await signUp(request, { email, display_name: name, side: "org", org: { legal_name: orgName, kind: "company" } });
  const { secret } = await post<{ secret: string }>(request, "/api/auth/totp/enrol", { password: PASSWORD });
  await post(request, "/api/auth/totp/confirm", { code: totp(secret) });
  const me = await request.get("/api/auth/me");
  const { memberships } = (await me.json()) as { memberships: Array<{ org_id: string; org_name: string }> };
  const orgId = memberships.find((m) => m.org_name === orgName)?.org_id;
  expect(orgId, "the new organisation").toBeTruthy();
  return { email, name, orgName, orgId: orgId!, domain, secret };
}

/**
 * The organisation's verification as a finished claim review would leave it. `e2`: verified on the member's domain,
 * the member also a signatory who accepted the current Master Enterprise Terms. `e1`: domain-verified only.
 */
export function verifyOrg(member: OrgMember, level: "e1" | "e2"): void {
  if (!TEST_DOMAIN.test(member.domain)) throw new Error("verifyOrg is for test organisations (*.example.com) only");
  const sql =
    level === "e2"
      ? "UPDATE organizations SET verification = 'e2', verified_domain = :'domain', e2_verified_at = now()" +
        " WHERE id = CAST(:'org' AS uuid);" +
        " UPDATE memberships SET roles = '{owner,admin,signatory}' WHERE org_id = CAST(:'org' AS uuid)" +
        " AND user_id = (SELECT id FROM users WHERE email = :'email');" +
        " INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)" +
        " SELECT gen_random_uuid(), CAST(:'org' AS uuid), u.id, t.id, t.sha256 FROM users u," +
        " legal_templates t WHERE u.email = :'email' AND t.id = app_current_legal_template('master_enterprise_terms');"
      : "UPDATE organizations SET verification = 'e1', verified_domain = :'domain' WHERE id = CAST(:'org' AS uuid);";
  ownerSql(sql, { domain: member.domain, org: member.orgId, email: member.email });
}

/** Removes the member's Tier-2 role (reviewer, signatory, admin): a plain viewer of the organisation. */
export function makeViewer(member: OrgMember): void {
  if (!TEST_DOMAIN.test(member.domain) || !member.email.endsWith(`@${member.domain}`)) {
    throw new Error("makeViewer is for test organisations (*.example.com) only");
  }
  ownerSql(
    "UPDATE memberships SET roles = '{owner,viewer}' WHERE org_id = CAST(:'org' AS uuid)" +
      " AND user_id = (SELECT id FROM users WHERE email = :'email');",
    { org: member.orgId, email: member.email },
  );
}

/** Leaves the member a reviewer only (a Tier-2 role that may change the shortlist, not sign or administer). */
export function makeReviewer(member: OrgMember): void {
  if (!TEST_DOMAIN.test(member.domain) || !member.email.endsWith(`@${member.domain}`)) {
    throw new Error("makeReviewer is for test organisations (*.example.com) only");
  }
  ownerSql(
    "UPDATE memberships SET roles = '{reviewer}' WHERE org_id = CAST(:'org' AS uuid)" +
      " AND user_id = (SELECT id FROM users WHERE email = :'email');",
    { org: member.orgId, email: member.email },
  );
}

/** A listed, unclaimed (E0) organisation of the seeded directory: a pitch there is held and reaches nobody. */
export function listedOrgId(): string {
  return ownerSql(
    "SELECT id FROM organizations WHERE verification = 'unclaimed' AND delisted_at IS NULL AND suspended_at IS NULL" +
      " ORDER BY random() LIMIT 1;",
    {},
  );
}

export interface Pitched {
  proposalId: string;
  title: string;
  certId: string;
}

/** The developer's side in its own browser context: sign up, D1, one published proposal, pitched to `orgIds`. */
export async function pitchFromNewDeveloper(browser: Browser, baseURL: string, orgIds: string[]): Promise<Pitched> {
  const context = await browser.newContext({ baseURL });
  try {
    const request = context.request;
    const id = tag();
    const email = `dev-${id}@example.com`;
    await signUp(request, { email, display_name: "Achieng Otieno", side: "developer" });
    ownerSql(
      "UPDATE developer_profiles SET verification_level = 'd1', updated_at = now()" +
        " WHERE verification_level = 'd0' AND user_id = (SELECT id FROM users WHERE email = :'email');",
      { email },
    );
    const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
      id: string;
      children?: Array<{ id: string }>;
    }>;
    const niche = niches.find((n) => n.children?.length)?.children?.[0]?.id ?? niches[0].id;
    const title = `Maziwa baridi ${id}`;
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
        new_problem: {
          title: `${title}: milk spoils`,
          statement: "Small dairy co-ops lose a fifth of the evening milk.",
        },
      },
      201,
    );
    const attestations = (await (await request.get("/api/proposals/attestations")).json()) as { version: string };
    const published = await post<{ cert_id: string }>(request, `/api/me/proposals/${draft.id}/publish`, {
      attestations: { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true },
      attestation_text_version: attestations.version,
    });
    await post(request, `/api/me/proposals/${draft.id}/tags`, { org_ids: orgIds }, 201);
    return { proposalId: draft.id, title, certId: published.cert_id };
  } finally {
    await context.close();
  }
}
