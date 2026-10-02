import { api, type ApiClient } from "@/lib/api/client";

// The Notifications page's two writes, from the browser (same-origin /api; the client adds the CSRF header). Both are
// the person's own state and idempotent on the API, so a retry is always safe.

const BOUND_MS = 4000;

/**
 * POST /api/me/notifications/{id}/read before the row's link is followed. Answers whether it was recorded; a failure
 * never stops the person from opening the row (the notification simply stays unread).
 */
export async function markRead(id: string, client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.POST("/api/me/notifications/{notification_id}/read", {
      params: { path: { notification_id: id } },
      signal: AbortSignal.timeout(BOUND_MS),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * POST /api/me/notifications/read-all: whether the API marked them (one that arrives meanwhile simply stays unread and
 * shows on the refreshed page).
 */
export async function markAllRead(client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.POST("/api/me/notifications/read-all", { signal: AbortSignal.timeout(BOUND_MS) });
    return response.ok;
  } catch {
    return false;
  }
}
