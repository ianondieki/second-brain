import {
  expect,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type BrowserContextOptions,
  type Page,
  type TestInfo,
} from "@playwright/test";

import { DEMO_PASSWORD } from "./moderation-scene";
import { demoTotpSecret, totp } from "./totp";
import { ownerSql as readAsOwner } from "./research-scene";
import { post } from "./tracker-scene";

/**
 * Telco A's seeded members for the P27 team and declaration specs (REQ-ENG-15, REQ-PROV-06): the demo seed
 * (`python -m bridge.seed --demo`; backend/src/bridge/seed/demo/data.py TELCO_A) gives Telco A (fixture), an E2
 * organisation, an owner and admin (Grace Mwangi), a signatory (Peter Kamau), a reviewer (Rita Njeri) and a finance
 * member (Faith Achieng); SACCO B (fixture)'s owner (David Kiprono) is a member of another organisation. Demo logins
 * share one public password and a TOTP key derived from the address (dev and test only). Each spec pitches a new
 * proposal to Telco A from a new developer, so no seeded engagement changes.
 */
export const TELCO_A = "Telco A (fixture)";

export const TELCO_A_MEMBERS = {
  owner: { email: "owner@telco-a.example", name: "Grace Mwangi" },
  signatory: { email: "signatory@telco-a.example", name: "Peter Kamau" },
  reviewer: { email: "reviewer@telco-a.example", name: "Rita Njeri" },
  finance: { email: "finance@telco-a.example", name: "Faith Achieng" },
} as const;
export const SACCO_B_OWNER = { email: "owner@sacco-b.example", name: "David Kiprono" } as const;

export type Seat = { email: string; name: string };

export interface Member {
  seat: Seat;
  page: Page;
  request: APIRequestContext;
  userId: string;
  orgId: string;
  close: () => Promise<void>;
}

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

/**
 * A code the API accepts now for a demo login: after the last one it accepted for the account (read by the owner),
 * never the window before the current one (see Person.code in tracker-scene).
 */
async function demoCode(email: string): Promise<string> {
  // A read only, of a demo account (the seed's addresses are under .example, never a real person's).
  if (!/@[a-z0-9-]+\.example$/.test(email)) throw new Error("demo accounts only");
  const stored = Number(
    readAsOwner("SELECT coalesce(totp_last_counter, 0) FROM users WHERE email = :'email';", { email }),
  );
  const now = Math.floor(Date.now() / 30_000);
  const counter = Math.max(stored + 1, now);
  if (counter > now + 1) await new Promise((r) => setTimeout(r, (counter - now - 1) * 30_000 + 1_000));
  return totp(demoTotpSecret(email), { time: counter * 30_000 });
}

/** Signs a seeded member in on a new browser context (the test's project's device), through the API. */
export async function signInMember(
  browser: Browser,
  info: TestInfo,
  seat: Seat,
  orgName = TELCO_A,
  options: BrowserContextOptions = {},
): Promise<Member> {
  const context: BrowserContext = await browser.newContext({ ...info.project.use, ...options });
  const page = await context.newPage();
  const request = page.request;
  const login = await request.post("/api/auth/login", {
    headers: { "X-CSRF-Token": await csrf(request) },
    data: { email: seat.email, password: DEMO_PASSWORD },
  });
  expect(login.status(), `${seat.email}: run python -m bridge.seed --demo (${await login.text()})`).toBe(200);
  if (((await login.json()) as { mfa_required?: boolean }).mfa_required) {
    await post(request, "/api/auth/mfa/verify", { code: await demoCode(seat.email) });
  }
  const me = (await (await request.get("/api/auth/me")).json()) as {
    user: { id: string };
    memberships: Array<{ org_id: string; org_name: string }>;
  };
  const orgId = me.memberships.find((m) => m.org_name === orgName)?.org_id;
  expect(orgId, `${seat.email} is a member of ${orgName}`).toBeTruthy();
  return { seat, page, request, userId: me.user.id, orgId: orgId!, close: () => context.close() };
}

/** The member accepts the Evaluation NDA for the proposal and opens its marked full details: one logged view. */
export async function viewFullProposal(member: Pick<Member, "orgId" | "request">, proposalId: string): Promise<void> {
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

/** A PUT, POST or DELETE with the CSRF header; the response for the caller to check. */
export async function send(
  request: APIRequestContext,
  method: "put" | "post" | "delete",
  path: string,
  data?: unknown,
) {
  return request[method](path, {
    headers: { "X-CSRF-Token": await csrf(request) },
    ...(data === undefined ? {} : { data }),
  });
}

/** The machine code of an API error response. */
export async function codeOf(response: { json: () => Promise<unknown> }): Promise<string | undefined> {
  const body = (await response.json()) as { detail?: { code?: string } };
  return body.detail?.code;
}

/** The proposal behind an engagement (the developer reads it). */
export async function proposalOf(request: APIRequestContext, engagementId: string): Promise<string> {
  const read = await request.get(`/api/engagements/${engagementId}`);
  expect(read.ok()).toBeTruthy();
  return ((await read.json()) as { proposal_id: string }).proposal_id;
}
