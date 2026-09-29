import { apiErrorCode, detailOf } from "@/lib/api/error-code";

import { isPitchReason, type PitchReason } from "./picker";

// What a Pitch or a withdrawal can answer, as the screens word it (REQ-PROP-03). The API's `detail.message` is never
// shown: every case has its own [[COPY-REVIEW]] string (pitch.problem.*, tagWithdraw.problem.*), so it can be translated
// and reviewed. Each refusal is one sentence and at most one action.

type Common = "signedOut" | "mfaRequired" | "rateLimited" | "unavailable" | "network" | "failed";

export type PitchProblem =
  | Common
  | "notFound"
  | "orgsGone"
  | "notPublic"
  | "d1Required"
  | "planLimit"
  | "planLimitUnknown"
  | "conflict"
  | "changed";

export interface PitchConflict {
  orgId: string;
  reason: PitchReason;
}

export interface PitchRefusal {
  problem: PitchProblem;
  /** 409 `tag_conflict`: the organisations that cannot be pitched to, in the order asked, with the reason code. */
  conflicts: PitchConflict[];
  /** 402 `plan_limit`: the plan's pitches per idea and how many are used. */
  limit?: number;
  used?: number;
}

function common(status: number, code: string | undefined): Common | null {
  if (status === 0) return "network";
  if (status === 401) return code === "mfa_required" ? "mfaRequired" : "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 503) return "unavailable";
  return null;
}

function conflictsOf(detail: Record<string, unknown> | undefined): PitchConflict[] {
  const list = detail?.conflicts;
  if (!Array.isArray(list)) return [];
  const out: PitchConflict[] = [];
  for (const item of list) {
    if (typeof item !== "object" || item === null) continue;
    const { org_id: orgId, reason } = item as Record<string, unknown>;
    if (typeof orgId === "string" && isPitchReason(reason)) out.push({ orgId: orgId.toLowerCase(), reason });
  }
  return out;
}

/** A refused Pitch (POST /api/me/proposals/{id}/tags). Nothing was created: the API refuses a batch whole. */
export function pitchRefusal(status: number, body: unknown): PitchRefusal {
  const code = apiErrorCode(body);
  const detail = detailOf(body);
  const shared = common(status, code);
  if (shared) return { problem: shared, conflicts: [] };
  if (status === 403 && code === "d1_required") return { problem: "d1Required", conflicts: [] };
  if (status === 402) {
    const { limit, used } = detail ?? {};
    if (typeof limit === "number" && typeof used === "number") {
      return { problem: "planLimit", conflicts: [], limit, used };
    }
    return { problem: "planLimitUnknown", conflicts: [] };
  }
  if (status === 404) {
    // The proposal is not the caller's (or was deleted), or some organisations left the directory (`org_ids`).
    return { problem: Array.isArray(detail?.org_ids) ? "orgsGone" : "notFound", conflicts: [] };
  }
  if (status === 409 && code === "proposal_not_public") return { problem: "notPublic", conflicts: [] };
  if (status === 409 && code === "tag_conflict") {
    const conflicts = conflictsOf(detail);
    // Without a list the API lost a race at the unique index: something changed between the check and the insert.
    return conflicts.length > 0 ? { problem: "conflict", conflicts } : { problem: "changed", conflicts: [] };
  }
  return { problem: "failed", conflicts: [] };
}

export type WithdrawProblem = Common | "notFound" | "closed" | "delivered";

/** A refused withdrawal (POST /api/me/proposals/{id}/tags/{tag_id}/withdraw). */
export function withdrawRefusal(status: number, body: unknown): WithdrawProblem {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return shared;
  if (status === 404) return "notFound";
  if (status === 409 && code === "tag_closed") return "closed";
  if (status === 409 && code === "tag_delivered") return "delivered";
  return "failed";
}
