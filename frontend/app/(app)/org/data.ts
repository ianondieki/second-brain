import { redirect } from "next/navigation";
import { cache } from "react";

import type { components } from "@/lib/api/schema";
import { forwardHeaders, requireMe, serverApi } from "@/lib/api/server";
import { homeFor, type Me } from "@/lib/auth/routing";

import { isUuid, orgQuery, pickMembership, type Membership } from "./membership";
import { refusalOf, type Refusal } from "./refusals";

// Server-side calls for the organisation screens, each bounded so a hung API ends in the route's error page. The
// session cookie is forwarded; the organisation is always one of the person's memberships (membership.ts).

export type InboxPage = components["schemas"]["InboxPage"];
export type InboxItem = components["schemas"]["InboxItem"];
export type OrgVerification = components["schemas"]["OrgVerification"];
export type TeaserCard = components["schemas"]["TeaserCard"];
export type Teaser = components["schemas"]["TeaserOut"];
export type EvaluationNda = components["schemas"]["EvaluationNdaOut"];

const TIMEOUT_MS = 5000;
/** Proposals per Inbox page: a phone's worth of teasers on mobile data. */
export const INBOX_PAGE_SIZE = 20;

export interface OrgContext {
  me: Me;
  memberships: Membership[];
  /** The organisation the screen acts for; null when there is none (see `missing`). */
  org: Membership | null;
  /** Why `org` is null: no active membership at all, or `?org=` names an organisation the person is not a member of. */
  missing: "none" | "notMember" | null;
  /** "?org=<id>" for links that keep the chosen organisation (empty for single-organisation members). */
  query: string;
}

/**
 * Organisation screens only: the signed-in person (else /login or the second-factor page), on the organisation side
 * (anyone else goes to their own home), and the organisation named by `?org=` when they are a member of it.
 */
export async function orgContext(requested: string | string[] | undefined): Promise<OrgContext> {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/org") redirect(home);
  const picked = pickMembership(me.memberships, requested);
  if (picked.kind !== "member") return { me, memberships: me.memberships, org: null, missing: picked.kind, query: "" };
  const org = picked.membership;
  return { me, memberships: me.memberships, org, missing: null, query: orgQuery(me.memberships, org.org_id) };
}

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/** The session ended between the page's /me check and this call: sign in again. */
function signInAgain(status: number) {
  if (status === 401) redirect("/login");
}

export type InboxResult =
  | { kind: "page"; page: InboxPage }
  | { kind: "staleCursor" }
  | { kind: "refused"; refusal: Refusal };

/**
 * One page of the organisation's Inbox (GET /api/orgs/{org_id}/inbox): delivered tags newest first. A cursor the API
 * no longer accepts (400) is "start again"; a second factor still owed or not set up is a refusal with its action.
 */
export async function getInbox(orgId: string, cursor?: string, limit = INBOX_PAGE_SIZE): Promise<InboxResult> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/inbox", {
    params: { path: { org_id: orgId }, query: { cursor, limit } },
    ...(await options()),
  });
  if (data) return { kind: "page", page: data };
  if (response.status === 400 && cursor) return { kind: "staleCursor" };
  const refusal = refusalOf(response.status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  signInAgain(response.status);
  if (refusal === "generic") throw new Error(`GET /api/orgs/{org_id}/inbox answered ${response.status}`);
  return { kind: "refused", refusal };
}

/**
 * A published teaser (Tier 1; GET /api/proposals/{id}), or null when there is none to show (a draft, a held or
 * hidden proposal and an unknown id all answer 404). Cached per request: the title and the page share one call.
 */
export const getTeaser = cache(async function getTeaser(proposalId: string): Promise<TeaserCard | null> {
  if (!isUuid(proposalId)) return null;
  const { data, response } = await serverApi().GET("/api/proposals/{proposal_id}", {
    params: { path: { proposal_id: proposalId } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 404) return null;
  signInAgain(response.status);
  throw new Error(`GET /api/proposals/{proposal_id} answered ${response.status}`);
});

export type NdaResult = { kind: "nda"; nda: EvaluationNda } | { kind: "refused"; refusal: Refusal };

/**
 * The Evaluation NDA for this proposal and organisation (GET …/nda), with this person's acceptance of it, or the
 * first condition that keeps the full proposal closed. Nothing Tier 2 is read here: the marked page is fetched by
 * the browser, inside the frame, only when the person opens it (each fetch is a logged view).
 */
export async function getNda(orgId: string, proposalId: string): Promise<NdaResult> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/proposals/{proposal_id}/nda", {
    params: { path: { org_id: orgId, proposal_id: proposalId } },
    ...(await options()),
  });
  if (data) return { kind: "nda", nda: data };
  const refusal = refusalOf(response.status, error);
  if (refusal !== "mfa_required") signInAgain(response.status);
  return { kind: "refused", refusal };
}

/** The same-origin address of the marked Tier-2 page (through the /api rewrite; the API allows framing by 'self'). */
export function tier2Src(orgId: string, proposalId: string): string {
  return `/api/orgs/${encodeURIComponent(orgId)}/proposals/${encodeURIComponent(proposalId)}/tier2`;
}
