import { withCsrf } from "@/lib/api/csrf";
import type { paths } from "@/lib/api/schema";

/** The two read markers, as the generated schema names them: a renamed route fails typecheck here. */
export type ReadPath = Extract<keyof paths, "/api/engagements/{engagement_id}/messages/read" | "/api/me/teams/{thread_id}/read">;
/** A read marker's body, from the same schema entry as its path. */
export type ReadBody<P extends ReadPath = ReadPath> = NonNullable<paths[P]["post"]>["requestBody"]["content"]["application/json"];

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/**
 * Moves a read marker up to a message the person has seen. It runs as a thread opens, so it carries only the CSRF
 * helper, not the typed client (that loads with Send: the messages routes stay within 150 KB, docs/spec/07 item 5);
 * the body's type still comes from the generated schema. Quiet: a refusal changes nothing on the page.
 */
export async function postReadMarker<P extends ReadPath>(path: P, id: string, upTo: string, send: Fetch = withCsrf()): Promise<boolean> {
  const body: ReadBody<P> = { up_to: upTo };
  try {
    const response = await send(path.replace(/\{[a-z_]+\}/, encodeURIComponent(id)), {
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
  return postReadMarker("/api/engagements/{engagement_id}/messages/read", engagementId, upTo, send);
}
