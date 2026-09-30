import { expect, type APIRequestContext } from "@playwright/test";

import { ownerSql, post, signUp, signUpOrg, tag, turnOnTotp, type OrgSide, type Person } from "./tracker-scene";

export { OWNER_DATABASE_URL } from "./tracker-scene";

/**
 * The Scout Agent walkthrough's state (REQ-SCOUT-02, M2 step 1), through the API wherever it has a path:
 *
 * - an E2 organisation (tracker-scene's signUpOrg) whose first member is also a reviewer, so the EM3 digest has a
 *   verified-domain seat to go to; its plan is upgraded through the simulated M-Pesa checkout (P14) to one with
 *   on_new scouts, so the developer's publication runs the scout at once (scouts.on_new in the worker);
 * - a developer who publishes one proposal in the scout's niche, mentioning its keyword, pitched to nobody.
 *
 * Only the member's roles and the developer's D1 level go through the database owner (no API sets them), for test
 * accounts only. E2E_DATABASE_OWNER_URL is required, as for the tracker specs.
 */

const ROLES = /^\{(owner|admin|signatory|reviewer|viewer|finance)(,(owner|admin|signatory|reviewer|viewer|finance))*\}$/;

/** Sets the organisation member's roles (for the reviewer refusal and back), e.g. "{owner,admin,reviewer}". */
export function setRoles(org: OrgSide, roles: string): void {
  if (!ROLES.test(roles)) throw new Error(`not a role list: ${roles}`);
  ownerSql(
    "UPDATE memberships SET roles = CAST(:'roles' AS org_role[]) WHERE org_id = CAST(:'org' AS uuid)" +
      " AND user_id = (SELECT id FROM users WHERE email = :'email');",
    { roles, org: org.orgId, email: org.person.email },
  );
}

/** A new E2 organisation whose first member is owner, admin, signatory and reviewer, signed in on `request`. */
export async function signUpScoutOrg(request: APIRequestContext): Promise<OrgSide> {
  const org = await signUpOrg(request);
  setRoles(org, "{owner,admin,signatory,reviewer}");
  return org;
}

/** Buys `plan` for the organisation through the simulated M-Pesa checkout and waits until it is active. */
export async function upgradeOrg(request: APIRequestContext, orgId: string, plan: string): Promise<void> {
  const checkout = await post<{ id: string }>(
    request,
    "/api/billing/checkouts",
    { plan_code: plan, org_id: orgId, simulate: "succeed" },
    201,
  );
  await expect(async () => {
    const response = await request.get(`/api/billing/checkouts/${checkout.id}`);
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as { status: string; plan_active: boolean };
    expect(body.status).toBe("succeeded");
    expect(body.plan_active).toBe(true);
  }).toPass({ timeout: 45_000, intervals: [1_000] });
}

export interface Niche {
  id: string;
  name: string;
}

/** A niche under a parent (the scout's niche and the proposal's). */
export async function childNiche(request: APIRequestContext): Promise<Niche> {
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
    id: string;
    name: string;
    children?: Array<{ id: string; name: string }>;
  }>;
  const child = niches.find((n) => n.children?.length)?.children?.[0];
  expect(child, "a niche with a parent").toBeTruthy();
  return { id: child!.id, name: child!.name };
}

export interface Published {
  person: Person;
  /**
   * The developer's display name: never shown to the organisation before INTEREST_CONFIRMED. The spec checks the name
   * as written; the handle itself is built from it (backend auth/service.py `_handle_from`: "achieng-otieno-2b2356"),
   * which is a backend follow-up (tasks/REQ-SCOUT-02.md, P10-F section), not something a screen can hide.
   */
  name: string;
  title: string;
  proposalId: string;
}

/**
 * A developer signed in on `request` (D1, two-step sign-in on) who publishes one proposal in `nicheId` whose title
 * and summary mention `keyword`, pitched to nobody: only a scout can bring it to an organisation.
 */
export async function publishUntagged(request: APIRequestContext, nicheId: string, keyword: string): Promise<Published> {
  const id = tag();
  const email = `dev-${id}@example.com`;
  const name = "Achieng Otieno";
  await signUp(request, { email, display_name: name, side: "developer" });
  const person = await turnOnTotp(request, email, name);
  ownerSql(
    "UPDATE developer_profiles SET verification_level = 'd1', updated_at = now()" +
      " WHERE verification_level = 'd0' AND user_id = (SELECT id FROM users WHERE email = :'email');",
    { email },
  );
  const title = `Chillers for ${keyword} co-ops ${id}`;
  const draft = await post<{ id: string }>(
    request,
    "/api/me/proposals",
    {
      teaser: {
        title,
        niche_id: nicheId,
        county_code: "KE-47",
        maturity: "mvp",
        ask: "pilot",
        problem_statement: "Milk spoils between the evening milking and the morning collection.",
        impact_claims: "Cuts spoilage for 40 farms.",
        summary: `Shared solar chillers for ${keyword} members, booked by SMS and paid per litre.`,
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
  return { person, name, title, proposalId: draft.id };
}
