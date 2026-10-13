import { forwardHeaders, serverApi } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

import { isInvitationToken } from "./paths";

export { invitationPath, isInvitationToken, joinPath } from "./paths";

// The invitation link's page (REQ-TEN-02; docs/platform/tasks/P28.md track C): what GET /api/invitations/{token}
// says before anyone signs in, the organisation's name and the roles, nothing else. The token is the link's
// capability: it goes to this site's API only (never a third party: the page's Referrer-Policy is no-referrer,
// security-headers.ts), and it is never logged here (the API's access log redacts the path).

export type InvitationPreview = components["schemas"]["InvitationPreview"];

export type InvitationRead =
  | { kind: "ok"; preview: InvitationPreview }
  /** Unknown, spent, revoked, resent-over or expired: one answer for all (the API's uniform 404). */
  | { kind: "gone" }
  /** Too many previews from this address in the last minute (429). */
  | { kind: "rateLimited" };

/**
 * The preview, read on the server with no session cookie (the token is the capability) and the visitor's forwarded
 * address only (the API's per-address limit counts the visitor, not this server). Bounded. A malformed token is
 * "gone" without a request; a 5xx or a timeout throws (the route's error page).
 */
export async function readInvitation(token: string): Promise<InvitationRead> {
  if (!isInvitationToken(token)) return { kind: "gone" };
  const { data, response } = await serverApi().GET("/api/invitations/{token}", {
    params: { path: { token } },
    headers: await forwardHeaders({ session: false }),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (data) return { kind: "ok", preview: data };
  if (response.status === 429) return { kind: "rateLimited" };
  if (response.status === 404 || response.status === 422) return { kind: "gone" };
  throw new Error(`GET /api/invitations/{token} answered ${response.status}`);
}
