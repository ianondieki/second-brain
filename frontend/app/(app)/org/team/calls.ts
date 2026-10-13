import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode, detailOf } from "@/lib/api/error-code";

import type { OrgRole } from "./team";

// The Team page's writes from the browser (REQ-TEN-02; docs/platform/tasks/P28.md track C). Each settles into "done"
// or a refusal the page words from its own strings (`teamAdmin.refusal.*`), never the server's text. `stepUp` is
// the API asking for a fresh second factor first (403 step_up_required): the page asks for the code, then repeats
// the call once.

/** Why a Team change did not happen, as the page says it. */
export type TeamRefusal =
  | "stepUp"
  | "invalid_email"
  | "already_member"
  | "already_invited"
  | "too_many_invitations"
  | "protected_role"
  | "invitation_closed"
  | "protected_member"
  | "last_owner"
  | "unknown_niche"
  | "invalid_default_reviewer"
  | "invalid_member"
  | "rate_limited"
  | "public_demo_locked"
  | "notAllowed"
  | "notFound"
  | "network"
  | "generic";

const BY_CODE: Record<string, TeamRefusal> = {
  step_up_required: "stepUp",
  invalid_email: "invalid_email",
  already_member: "already_member",
  already_invited: "already_invited",
  too_many_invitations: "too_many_invitations",
  protected_role: "protected_role",
  invitation_closed: "invitation_closed",
  protected_member: "protected_member",
  last_owner: "last_owner",
  // A niche gone from the catalogue and a niche sent twice read the same: the page is out of date.
  unknown_niche: "unknown_niche",
  duplicate_niche: "unknown_niche",
  invalid_default_reviewer: "invalid_default_reviewer",
  invalid_member: "invalid_member",
  rate_limited: "rate_limited",
  public_demo_locked: "public_demo_locked",
};

/** The refusal for an answer's status and error body. */
export function teamRefusal(status: number, error: unknown): TeamRefusal {
  const code = apiErrorCode(error);
  if (code && code in BY_CODE) return BY_CODE[code];
  if (status === 404) return "notFound";
  if (status === 403) return "notAllowed";
  if (status === 429) return "rate_limited";
  return "generic";
}

export type TeamOutcome<T = null> =
  | { ok: true; value: T }
  | { ok: false; refusal: TeamRefusal; /** too_many_invitations: the cap the API names. */ limit?: number };

async function settle<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<TeamOutcome<T | null>> {
  try {
    const { data, error, response } = await call;
    if (response.ok) return { ok: true, value: data ?? null };
    const limit = detailOf(error)?.limit;
    return { ok: false, refusal: teamRefusal(response.status, error), ...(typeof limit === "number" ? { limit } : {}) };
  } catch {
    return { ok: false, refusal: "network" };
  }
}

export interface TeamCalls {
  invite: (email: string, roles: OrgRole[]) => Promise<TeamOutcome<unknown>>;
  resend: (invitationId: string) => Promise<TeamOutcome<unknown>>;
  revoke: (invitationId: string) => Promise<TeamOutcome<unknown>>;
  remove: (userId: string) => Promise<TeamOutcome<unknown>>;
  setRoles: (userId: string, roles: OrgRole[]) => Promise<TeamOutcome<unknown>>;
  setNicheDefaults: (items: { niche_slug: string; user_id: string }[]) => Promise<TeamOutcome<unknown>>;
  setEscalationContact: (userId: string | null) => Promise<TeamOutcome<unknown>>;
}

/** The calls for one organisation. */
export function teamCalls(orgId: string, client: ApiClient = api): TeamCalls {
  const org = { org_id: orgId };
  return {
    invite: (email, roles) =>
      settle(client.POST("/api/orgs/{org_id}/invitations", { params: { path: org }, body: { email, roles } })),
    resend: (invitationId) =>
      settle(
        client.POST("/api/orgs/{org_id}/invitations/{invitation_id}/resend", {
          params: { path: { ...org, invitation_id: invitationId } },
        }),
      ),
    revoke: (invitationId) =>
      settle(
        client.DELETE("/api/orgs/{org_id}/invitations/{invitation_id}", {
          params: { path: { ...org, invitation_id: invitationId } },
        }),
      ),
    remove: (userId) =>
      settle(client.DELETE("/api/orgs/{org_id}/members/{user_id}", { params: { path: { ...org, user_id: userId } } })),
    setRoles: (userId, roles) =>
      settle(
        client.PUT("/api/orgs/{org_id}/members/{user_id}/roles", {
          params: { path: { ...org, user_id: userId } },
          body: { roles },
        }),
      ),
    setNicheDefaults: (items) =>
      settle(client.PUT("/api/orgs/{org_id}/niche-defaults", { params: { path: org }, body: { items } })),
    setEscalationContact: (userId) =>
      settle(client.PUT("/api/orgs/{org_id}/escalation-contact", { params: { path: org }, body: { user_id: userId } })),
  };
}
