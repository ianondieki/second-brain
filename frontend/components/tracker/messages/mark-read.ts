import { api, type ApiClient } from "@/lib/api/client";

/** Moves the caller's read marker up to a message they have seen. Quiet: a refusal changes nothing on the page. */
export async function markRead(engagementId: string, upTo: string, client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.POST("/api/engagements/{engagement_id}/messages/read", {
      params: { path: { engagement_id: engagementId } },
      body: { up_to: upTo },
    });
    return response.ok;
  } catch {
    return false;
  }
}
