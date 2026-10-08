import { apiOrigin, forwardHeaders, recordAppNow } from "@/lib/api/server";

import { parseActivity, WEEKS, type Activity } from "./calendar";

/**
 * The signed-in person's own activity (GET /api/me/activity?weeks=26), read on the server with the page, or null when
 * there is no answer in time or it has another shape: the calendar's card is then left out, never the page.
 */
export async function getActivity(weeks: number = WEEKS): Promise<Activity | null> {
  try {
    const headers = await forwardHeaders();
    if (!headers.cookie) return null;
    const response = await fetch(`${apiOrigin}/api/me/activity?weeks=${weeks}`, {
      headers: { ...headers, accept: "application/json" },
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    recordAppNow(response);
    if (!response.ok) return null;
    return parseActivity(await response.json());
  } catch {
    return null;
  }
}
