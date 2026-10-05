import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { PreferenceItem } from "./choices";

/**
 * The signed-in person's notification preferences (GET /api/me/notification-preferences): a store apart from the
 * consents, listing only what this person may set (the saved-search digest for developers, P21). A failed read (an
 * error, no answer in time, the network) is no preferences, so the consents above still work; only a lost session
 * (401) leaves, to sign in again.
 */
export async function myPreferences(): Promise<PreferenceItem[]> {
  let answer;
  try {
    answer = await serverApi().GET("/api/me/notification-preferences", {
      headers: await forwardHeaders(),
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
    });
  } catch {
    return [];
  }
  if (answer.data) return answer.data.items;
  if (answer.response.status === 401) redirect("/login"); // the session ended between the page's /me check and this
  return [];
}
