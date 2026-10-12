import type { components } from "@/lib/api/schema";
import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";

// The Team sheet's calls from the browser (REQ-ENG-15; D-68): the organisation's own triage of one engagement, under
// /api/orgs/{org_id}/engagements/{engagement_id}. Each settles into the API's answer or a refusal the sheet words
// from its own strings (`teamSheet.refusal.*`), never the server's text. Loaded with the sheet, never on the
// tracker's first load.

type Schemas = components["schemas"];
export type Team = Schemas["TeamOut"];
export type TeamMember = Schemas["TeamMemberOut"];
export type Recommendation = Schemas["RecommendationOut"];
export type Stance = Schemas["RecommendationStance"];

export const STANCES = ["pursue", "pass", "discuss"] as const satisfies readonly Stance[];
/** A recommendation's note: one line, at most 200 characters (engagements/models.py RECOMMENDATION_NOTE_MAX_CHARS). */
export const NOTE_MAX = 200;

/** Why a team change was refused, as the sheet says it. */
export type TeamRefusal =
  | "notAllowed"
  | "invalidAssignee"
  | "unchanged"
  | "conflict"
  | "tooMany"
  | "invalidNote"
  | "notFound"
  | "network"
  | "generic";

const BY_CODE: Record<string, TeamRefusal> = {
  role_not_allowed: "notAllowed",
  invalid_assignee: "invalidAssignee",
  unchanged: "unchanged",
  conflict: "conflict",
  too_many_assignments: "tooMany",
  invalid_note: "invalidNote",
};

export function teamRefusal(status: number, error: unknown): TeamRefusal {
  const code = apiErrorCode(error);
  if (code && code in BY_CODE) return BY_CODE[code];
  if (status === 404) return "notFound";
  if (status === 403) return "notAllowed";
  if (status === 409) return "conflict";
  if (status === 429) return "tooMany";
  if (status === 422) return code === "validation" ? "invalidNote" : "generic";
  return "generic";
}

export type TeamOutcome = { ok: true; team: Team } | { ok: false; refusal: TeamRefusal };

export interface TeamCalls {
  read: () => Promise<TeamOutcome>;
  assign: (userId: string | null) => Promise<TeamOutcome>;
  recommend: (stance: Stance, note: string) => Promise<TeamOutcome>;
  withdraw: () => Promise<TeamOutcome>;
}

/** The calls for one engagement of one organisation. */
export function teamCalls(orgId: string, engagementId: string, client: ApiClient = api): TeamCalls {
  const params = { path: { org_id: orgId, engagement_id: engagementId } };
  async function settle(call: Promise<{ data?: Team; error?: unknown; response: Response }>): Promise<TeamOutcome> {
    try {
      const { data, error, response } = await call;
      return data ? { ok: true, team: data } : { ok: false, refusal: teamRefusal(response.status, error) };
    } catch {
      return { ok: false, refusal: "network" };
    }
  }
  return {
    read: () => settle(client.GET("/api/orgs/{org_id}/engagements/{engagement_id}/team", { params })),
    assign: (userId) =>
      settle(
        client.PUT("/api/orgs/{org_id}/engagements/{engagement_id}/assignee", { params, body: { user_id: userId } }),
      ),
    recommend: (stance, note) =>
      settle(
        client.PUT("/api/orgs/{org_id}/engagements/{engagement_id}/recommendation", {
          params,
          body: { stance, note: note.trim() || null },
        }),
      ),
    withdraw: () => settle(client.DELETE("/api/orgs/{org_id}/engagements/{engagement_id}/recommendation", { params })),
  };
}
