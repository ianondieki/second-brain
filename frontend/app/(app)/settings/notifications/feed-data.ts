import type { components } from "@/lib/api/schema";
import { forwardHeaders, serverApi } from "@/lib/api/server";

export type FeedStatus = components["schemas"]["CalendarFeedStatus"];

/**
 * Whether the person's calendar feed is live (GET /api/me/calendar-feed, or the organisation's for them): the link
 * itself is never read back (the API keeps only its hash). Null when it cannot be read: the section then offers only
 * to create one.
 */
export async function feedStatus(orgId?: string): Promise<FeedStatus | null> {
  const init = { headers: await forwardHeaders(), signal: AbortSignal.timeout(5000), cache: "no-store" as const };
  try {
    const { data } = orgId
      ? await serverApi().GET("/api/orgs/{org_id}/calendar-feed", { params: { path: { org_id: orgId } }, ...init })
      : await serverApi().GET("/api/me/calendar-feed", init);
    return data ?? null;
  } catch {
    return null;
  }
}
