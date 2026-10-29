import type { components } from "@/lib/api/schema";

// The claims queue's pure parts (REQ-DIR-03 queue, REQ-ADM-01; docs/spec/06 6.2 "admin claim queue with the 2 BD SLA
// shown", 6.12; PLAN §8 P15): which view a query asks for, the review time left as a mark and words, and how an
// organisation staff cannot read is named. Read only: the prototype decides no claim.

export type Claim = components["schemas"]["ClaimOut"];
export type ClaimDetail = components["schemas"]["ClaimDetailOut"];
export type ClaimSla = components["schemas"]["ClaimSla"];
export type ClaimStatus = Claim["status"];

export const CLAIMS_PATH = "/admin/claims";

/** The queue's views: awaiting staff review (the default), awaiting the claimant, and closed. */
export const CLAIM_VIEWS = ["review", "in_progress", "closed"] as const;
export type ClaimView = (typeof CLAIM_VIEWS)[number];

/** `?view=` of the claims queue; anything unknown opens the claims awaiting review. */
export function claimView(value: string | undefined): ClaimView {
  return (CLAIM_VIEWS as readonly string[]).includes(value ?? "") ? (value as ClaimView) : "review";
}

export function claimViewHref(view: ClaimView): string {
  return view === "review" ? CLAIMS_PATH : `${CLAIMS_PATH}?view=${view}`;
}

export function claimHref(claimId: string): string {
  return `${CLAIMS_PATH}/${encodeURIComponent(claimId)}`;
}

/**
 * The review time left, shown as a mark and words, never colour alone (docs/spec/07 item 6): overdue once past the
 * end of the due day, "today" on it, else the Kenyan business days left (the API counts them). Null without an SLA
 * (only a claim awaiting review has one).
 */
export type SlaState = { kind: "overdue" } | { kind: "today" } | { kind: "due"; days: number };

export function slaState(sla: Pick<ClaimSla, "overdue" | "business_days_left"> | null): SlaState | null {
  if (!sla) return null;
  if (sla.overdue || sla.business_days_left < 0) return { kind: "overdue" };
  if (sla.business_days_left === 0) return { kind: "today" };
  return { kind: "due", days: sla.business_days_left };
}

/** The tracker chip each SLA state wears (⚠ overdue; ● current otherwise). */
export function slaChip(state: SlaState): "overdue" | "current" {
  return state.kind === "overdue" ? "overdue" : "current";
}

/** The tracker chip a claim's status wears when it has no SLA to show. */
export const STATUS_CHIP = {
  otp_sent: "pending",
  dns_pending: "pending",
  pending_review: "current",
  disputed: "onHold",
  approved: "completed",
  rejected: "ended",
  withdrawn: "ended",
} as const satisfies Record<ClaimStatus, string>;

/**
 * The organisation's name, or null when staff cannot read it (Row-Level Security admits listed organisations only:
 * a delisted, pending or rejected one comes back as its id alone).
 */
export function orgName(org: Pick<Claim["org"], "legal_name">): string | null {
  return org.legal_name?.trim() || null;
}

/** The first block of an id, enough to tell organisations apart in a list (the detail page shows it whole). */
export function shortId(id: string): string {
  return id.split("-")[0] ?? id;
}
