import { detailOf, isRecord } from "@/lib/api/error-code";

// The way from a 402 plan-limit refusal to the checkout (REQ-BIL-08, docs/spec/05). The API's body names the next
// plan up (`detail.upgrade.plan`, null at the top of the ladder); the link is built here from that code alone, so no
// URL from a response body is ever followed.

export const UPGRADE_PATH = "/billing/upgrade";
export const BILLING_PATH = "/billing";

/** A plan code as plans.yaml writes them ("dev_pro_monthly"); anything else is never put in a link. */
const PLAN_CODE = /^[a-z][a-z0-9_]{0,39}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** Where a finished checkout may send the person back to: a signed-in page of this site, nothing else. */
const NEXT_PATH = /^\/(dev|org)(\/[A-Za-z0-9._~\-/]*)?(\?[A-Za-z0-9._~\-=&%]*)?$/;

export function isPlanCode(value: unknown): value is string {
  return typeof value === "string" && PLAN_CODE.test(value);
}

export function isOrgId(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * The page a finished checkout offers to go back to, or undefined. Only "/dev…" and "/org…" paths of this site with
 * plain characters: no scheme, no host, no "//", no backslash, no "..", so the link can never leave the site.
 */
export function safeNext(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 300 || !NEXT_PATH.test(value)) return undefined;
  if (value.includes("//") || value.split(/[/?]/).some((segment) => segment === "." || segment === "..")) {
    return undefined;
  }
  return value;
}

/** The next plan up that a 402 `plan_limit` body names, or null (top of the ladder, or not a plan-limit body). */
export function upgradePlanOf(body: unknown): string | null {
  const upgrade = detailOf(body)?.upgrade;
  if (!isRecord(upgrade)) return null;
  return isPlanCode(upgrade.plan) ? upgrade.plan : null;
}

/** "/billing/upgrade?plan=dev_pro_monthly", with the organisation and the page to come back to when given. */
export function upgradeHref(plan: string, { org, next }: { org?: string; next?: string } = {}): string {
  const params = new URLSearchParams({ plan });
  if (org && isOrgId(org)) params.set("org", org);
  const back = safeNext(next);
  if (back) params.set("next", back);
  return `${UPGRADE_PATH}?${params.toString()}`;
}

/** "/billing", or "/billing?org=<id>" for an organisation's plan. */
export function billingHref(org?: string): string {
  return org && isOrgId(org) ? `${BILLING_PATH}?org=${org}` : BILLING_PATH;
}
