import { withCsrf } from "@/lib/api/csrf";
import type { operations } from "@/lib/api/schema";

type Engagement = operations["mark_read_api_engagements__engagement_id__messages_read_post"];
type Team = operations["mark_read_api_me_teams__thread_id__read_post"];
/** The read marker's body as both endpoints take it (from the generated schema). */
export type ReadBody = Engagement["requestBody"]["content"]["application/json"] & Team["requestBody"]["content"]["application/json"];

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/**
 * Moves a read marker up to a message the person has seen. It runs as a thread opens, so it carries only the CSRF
 * helper, not the typed client (that loads with Send: the messages routes stay within 150 KB, docs/spec/07 item 5);
 * the body's type still comes from the generated schema. Quiet: a refusal changes nothing on the page.
 */
export async function postReadMarker(url: string, upTo: string, send: Fetch = withCsrf()): Promise<boolean> {
  const body: ReadBody = { up_to: upTo };
  try {
    const response = await send(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** POST /api/engagements/{engagement_id}/messages/read */
export function markRead(engagementId: string, upTo: string, send?: Fetch): Promise<boolean> {
  return postReadMarker(`/api/engagements/${encodeURIComponent(engagementId)}/messages/read`, upTo, send);
}
