// The account menu's "Plan & billing" link (on every signed-in page) without importing lib/billing/upgrade.ts, whose
// checkout helpers cost about 0.5 KB gzipped on every route (docs/spec/07 item 5; P16-C1 found /settings/security at
// the 150 KB budget). Same rule as its billingHref; billing-link.test.ts keeps the two in step.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** "/billing", or "/billing?org=<id>" when `org` is an organisation id (anything else is never put in the link). */
export function menuBillingHref(org: string | null | undefined): string {
  return org && UUID.test(org) ? `/billing?org=${org}` : "/billing";
}
