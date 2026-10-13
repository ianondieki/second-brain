// Why an export did not download (REQ-ENG-17), as the Engagements list says it from ?export=<why>. Pure: the route
// handler, the list page and their tests share it.

export const EXPORT_REFUSALS = ["plan", "rateLimited", "signedOut", "notFound", "failed"] as const;
export type ExportRefusal = (typeof EXPORT_REFUSALS)[number];

/** The refusal for an API answer that was not the file. */
export function exportOutcome(status: number, code: string | undefined): ExportRefusal {
  if (status === 402 || code === "plan_limit" || code === "entitlement_required") return "plan";
  if (status === 429) return "rateLimited";
  if (status === 401) return "signedOut";
  if (status === 404) return "notFound";
  return "failed";
}

/** The list's address that says it: /org/engagements?export=<why>[&org=<id>][&retry=<seconds>]. */
export function exportRefusalHref(refusal: ExportRefusal, org: string | null, retryAfter?: number | null): string {
  const params = new URLSearchParams({ export: refusal });
  if (org) params.set("org", org);
  if (retryAfter !== null && retryAfter !== undefined) params.set("retry", String(retryAfter));
  return `/org/engagements?${params.toString()}`;
}

/** A page's ?export= value, when it is one of the refusals. */
export function exportRefusalParam(value: string | string[] | undefined): ExportRefusal | null {
  const first = Array.isArray(value) ? value[0] : value;
  return (EXPORT_REFUSALS as readonly string[]).includes(first ?? "") ? (first as ExportRefusal) : null;
}
