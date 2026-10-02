import type { ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

// The editor's two teaser checks (REQ-PROP-04 originality, REQ-REPO-01 over-disclosure, warn only; docs/spec/06 6.1,
// 6.3). Both read the saved draft's four Tier-1 fields; neither changes the idea or stands in the way of publishing.
// Each call settles into its value or a problem the card words with a fixed [[COPY-REVIEW]] sentence (ideaChecks.problem.*,
// or the assistant's own for the codes the two share): the API's `message` is never shown.
//
// Like assistant.ts, nothing here imports the API client at the top: the typed client comes from the editor's save
// chunk when a check runs, so this module adds nothing to the page (docs/spec/07 item 5).

type Schemas = components["schemas"];
export type Originality = Schemas["OriginalityOut"];
export type DisclosureCheck = Schemas["DisclosureCheckOut"];
export type TeaserField = Schemas["TeaserField"];

/** The checks' own refusal codes (bridge/proposals/originality_router.py, disclosure_router.py, assistant.refusal). */
export type CheckCode =
  | "originality_busy"
  | "originality_limit"
  | "disclosure_busy"
  | "disclosure_rate_limited"
  | "assistant_budget"
  | "assistant_paused"
  | "assistant_off";

/** Why a check did not answer: its own code, or one every editor call shares. */
export type CheckProblem =
  | CheckCode
  | "signedOut"
  | "mfaRequired"
  | "rateLimited"
  | "notFound"
  | "hidden"
  | "unavailable"
  | "network"
  | "failed";

export type CheckOutcome<T> = { ok: true; value: T } | { ok: false; problem: CheckProblem };

const OWN = /^(originality_(busy|limit)|disclosure_(busy|rate_limited)|assistant_(budget|paused|off))$/;

/** A refused check: its own codes first (a 503 `assistant_off` is not a generic outage), then the shared ones. */
export function checkRefusal(status: number, body: unknown): CheckProblem {
  const detail = (body as { detail?: { code?: unknown } } | null | undefined)?.detail;
  const code = typeof detail === "object" && detail !== null ? detail.code : undefined;
  if (typeof code === "string" && OWN.test(code)) return code as CheckCode;
  if (status === 0) return "network";
  if (status === 401) return code === "mfa_required" ? "mfaRequired" : "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 404) return "notFound";
  if (status === 409 && code === "proposal_hidden") return "hidden";
  return status === 503 ? "unavailable" : "failed";
}

type Answer = { data?: unknown; error?: unknown; response: Response };

async function settle<T>(call: (client: ApiClient) => Promise<Answer>, client?: ApiClient): Promise<CheckOutcome<T>> {
  try {
    const answer = await call(client ?? (await import("./save")).api);
    return answer.response.ok
      ? { ok: true, value: answer.data as T }
      : { ok: false, problem: checkRefusal(answer.response.status, answer.error) };
  } catch {
    return { ok: false, problem: "network" };
  }
}

const path = (id: string) => ({ params: { path: { proposal_id: id } } });

/** How close the saved teaser reads to other developers' published teasers: a band, never a score. */
export function overlap(id: string, client?: ApiClient) {
  return settle<Originality>((api) => api.POST("/api/me/proposals/{proposal_id}/originality", path(id)), client);
}

/** Whether the saved teaser gives away how the project works. A warning only. */
export function disclosure(id: string, client?: ApiClient) {
  return settle<DisclosureCheck>((api) => api.POST("/api/me/proposals/{proposal_id}/disclosure-check", path(id)), client);
}

/** What the checks card calls (its tests pass fakes). */
export interface ChecksCalls {
  overlap: typeof overlap;
  disclosure: typeof disclosure;
}

/** The sentence of an overlap answer (ideaChecks.overlap.*): "none" says how many it was compared with. */
export function overlapKey({ band, compared }: Pick<Originality, "band" | "compared">) {
  return `overlap.${band === "none" && compared === 0 ? "noneEmpty" : band}` as const;
}

/** The labels docs/spec/09 puts on AI output, in the assistant's order: at most two (docs/spec/07 item 2). */
export function chipsOf({ ai_drafted, demo_fallback }: { ai_drafted: boolean; demo_fallback: boolean }) {
  return [...(ai_drafted ? ["aiDrafted" as const] : []), ...(demo_fallback ? ["demoFallback" as const] : [])];
}
