import { forwardHeaders, serverApi } from "@/lib/api/server";
import { refused, type Read } from "@/components/tracker/data";

import type { Deadline } from "./month";

// Server-side reads for the Calendar tab (P27 track A; REQ-ENG-13), bounded and with the session forwarded, as the
// tracker's (components/tracker/data.ts).

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export interface Deadlines {
  items: Deadline[];
  /** The platform clock the list was read at. */
  now: string;
}

/**
 * The caller's deadlines (GET /api/me/deadlines, or the organisation's with `orgId`). `from` omitted: every overdue
 * item and what falls due up to `to`; both given: the days between, inclusive (Nairobi dates).
 */
export async function readDeadlines(span: { from?: string; to: string }, orgId?: string): Promise<Read<Deadlines>> {
  const query = { from: span.from, to: span.to };
  const { data, error, response } = orgId
    ? await serverApi().GET("/api/orgs/{org_id}/deadlines", {
        params: { path: { org_id: orgId }, query },
        ...(await options()),
      })
    : await serverApi().GET("/api/me/deadlines", { params: { query }, ...(await options()) });
  if (data) return { ok: true, value: { items: data.items, now: data.now } };
  return {
    ok: false,
    refusal: refused(response.status, error, orgId ? "GET /api/orgs/{org_id}/deadlines" : "GET /api/me/deadlines"),
  };
}

/** A deadline's `.ics` file (same-origin /api, the browser's session): the caller's own, or the organisation's. */
export function icsHref(kind: string, id: string, orgId?: string): string {
  const tail = `deadlines/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/calendar.ics`;
  return orgId ? `/api/orgs/${encodeURIComponent(orgId)}/${tail}` : `/api/me/${tail}`;
}
