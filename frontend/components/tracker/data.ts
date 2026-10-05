import { redirect } from "next/navigation";
import { cache } from "react";

import { apiErrorCode } from "@/lib/api/error-code";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { Member } from "./CommandForm";
import type { Detail, DocumentKind, History, Summary } from "./model";
import type { Thread } from "./messages/thread";
import type { Tier2Share } from "./share";

// Server-side reads for the tracker screens (signed in only). Each call is bounded, so a hung API ends in the route's
// error page instead of a page that never renders; the session cookie is forwarded.

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/** Why an engagement read was refused, as the screens word it (`tracker.refused.*`). */
export type ReadRefusal = "notFound" | "mfaSetup" | "bothParties";

function refused(status: number, error: unknown, path: string): ReadRefusal {
  // The session ended between the page's /me check and this call, or still owes its second factor.
  if (status === 401) redirect(apiErrorCode(error) === "mfa_required" ? "/auth/mfa" : "/login");
  const code = apiErrorCode(error);
  if (status === 404) return "notFound";
  if (code === "mfa_enrolment_required") return "mfaSetup";
  if (code === "both_parties") return "bothParties";
  throw new Error(`${path} answered ${status}`);
}

export type Read<T> = { ok: true; value: T } | { ok: false; refusal: ReadRefusal };

/** The developer's engagements, newest change first (GET /api/me/engagements). */
export async function myEngagements(): Promise<Summary[]> {
  const { data, error, response } = await serverApi().GET("/api/me/engagements", await options());
  if (data) return data.items;
  refused(response.status, error, "GET /api/me/engagements");
  throw new Error(`GET /api/me/engagements answered ${response.status}`);
}

/** An organisation's engagements (GET /api/orgs/{org_id}/engagements; any member). */
export async function orgEngagements(orgId: string): Promise<Read<Summary[]>> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/engagements", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (data) return { ok: true, value: data.items };
  return { ok: false, refusal: refused(response.status, error, "GET /api/orgs/{org_id}/engagements") };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isEngagementId(value: string): boolean {
  return UUID.test(value);
}

/** One engagement as the caller sees it, with their buttons. Cached per request (the title and the page share it). */
export const engagement = cache(async function engagement(id: string): Promise<Read<Detail>> {
  if (!isEngagementId(id)) return { ok: false, refusal: "notFound" };
  const { data, error, response } = await serverApi().GET("/api/engagements/{engagement_id}", {
    params: { path: { engagement_id: id } },
    ...(await options()),
  });
  if (data) return { ok: true, value: data };
  return { ok: false, refusal: refused(response.status, error, "GET /api/engagements/{engagement_id}") };
});

/** The History tab: the same events for both parties. */
export const engagementHistory = cache(async function engagementHistory(id: string): Promise<History | null> {
  const { data, error, response } = await serverApi().GET("/api/engagements/{engagement_id}/history", {
    params: { path: { engagement_id: id } },
    ...(await options()),
  });
  if (data) return data;
  refused(response.status, error, "GET /api/engagements/{engagement_id}/history");
  return null;
});

export type ThreadRead =
  | { kind: "open"; thread: Thread }
  | { kind: "notOpen" }
  | { kind: "refused"; refusal: ReadRefusal };

/**
 * The Messages tab's first page (REQ-ENG-11; GET …/messages): the latest messages, the thread's state and what the
 * caller may do. The organisation is refused (403 thread_not_open) until the engagement reaches INTEREST_CONFIRMED
 * (AC-TRACK-9): the tab then says when it opens, as it does for the developer's not-yet-open thread. Any other
 * refusal (the engagement is gone or no longer the caller's: 404) is said as the tracker says it.
 */
export async function engagementThread(id: string): Promise<ThreadRead> {
  const { data, error, response } = await serverApi().GET("/api/engagements/{engagement_id}/messages", {
    params: { path: { engagement_id: id } },
    ...(await options()),
  });
  if (data) return data.status === "not_open" ? { kind: "notOpen" } : { kind: "open", thread: data };
  if (response.status === 403 && apiErrorCode(error) === "thread_not_open") return { kind: "notOpen" };
  return { kind: "refused", refusal: refused(response.status, error, "GET /api/engagements/{engagement_id}/messages") };
}

export type DocumentText = { kind: DocumentKind; ref: string; sha256: string; text: string; intact: boolean };

/** The exact text of a document of the engagement (the NDA, the agreement, the acceptance certificate). */
export async function engagementDocument(id: string, kind: DocumentKind): Promise<DocumentText | null> {
  const { data, error, response } = await serverApi().GET("/api/engagements/{engagement_id}/documents/{kind}", {
    params: { path: { engagement_id: id, kind } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 404 || response.status === 409) return null;
  refused(response.status, error, "GET /api/engagements/{engagement_id}/documents/{kind}");
  return null;
}

/**
 * The organisation's active members (the approve form's contact person), or null when they could not be read: the
 * form then says so instead of offering an empty list.
 */
export async function orgMembers(orgId: string): Promise<Member[] | null> {
  const { data, response } = await serverApi().GET("/api/orgs/{org_id}/members", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (response.status === 401) redirect("/login");
  return data ? data.map((m) => ({ user_id: m.user_id, display_name: m.display_name })) : null;
}

/**
 * Whether the developer shared the full proposal with the organisation (GET …/share-tier2; both parties), or null
 * when it could not be read (the section is then left out rather than guessing).
 */
export async function tier2ShareState(id: string): Promise<Tier2Share | null> {
  const { data, response } = await serverApi().GET("/api/engagements/{engagement_id}/share-tier2", {
    params: { path: { engagement_id: id } },
    ...(await options()),
  });
  if (response.status === 401) redirect("/login");
  return data ?? null;
}
