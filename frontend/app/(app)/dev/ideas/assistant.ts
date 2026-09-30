import type { ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

// The submission assistant's calls (REQ-PROP-05; docs/spec/06 6.3, docs/spec/09). They load with the editor's
// assistant panel, when the owner opens it, never with the page. Each settles into its value or a problem the panel
// words with its own [[COPY-REVIEW]] string (ideaAssistant.problem.*): the API's `message` and `detail.message` are
// never shown.
//
// Nothing here imports the API client, outcomes.ts or error-code.ts at the top: a module imported statically is copied
// into the panel's chunk even when the editor's save chunk already holds it (docs/spec/07 item 5: the editor is close
// to 150 KB). The typed client comes from the save chunk itself, which the first edit has usually loaded already.

type Schemas = components["schemas"];
export type AssistantConsent = Schemas["AssistantConsentOut"];
export type AssistantSuggestion = Schemas["AssistantSuggestionOut"];
export type PlacementHint = Schemas["PlacementHintOut"];
export type SuggestedTeaser = Schemas["SuggestedTeaserOut"];

/** The assistant's own refusal codes (bridge/proposals/assistant.py, assistant_router.py, access.tier2_gate). */
export type AssistantCode =
  | "consent_required"
  | "consent_text_changed"
  | "assistant_busy"
  | "assistant_rate_limited"
  | "assistant_budget"
  | "assistant_paused"
  | "assistant_off"
  | "assistant_demo_only"
  | "tier2_disabled";

/** Why the assistant did not answer: its own code, or one every editor call shares (as outcomes.ts `common`). */
export type AssistantProblem =
  | AssistantCode
  | "signedOut"
  | "mfaRequired"
  | "rateLimited"
  | "notFound"
  | "hidden"
  | "unavailable"
  | "network"
  | "failed";

export type AssistantOutcome<T> = { ok: true; value: T } | { ok: false; problem: AssistantProblem };

const OWN = /^(consent_(required|text_changed)|assistant_(busy|rate_limited|budget|paused|off|demo_only)|tier2_disabled)$/;

/**
 * A refused assistant call: its own codes first (a 503 `assistant_off` is not a generic outage), then the ones every
 * editor call shares, by status.
 */
export function assistantRefusal(status: number, body: unknown): AssistantProblem {
  const detail = (body as { detail?: { code?: unknown } } | null | undefined)?.detail;
  const code = typeof detail === "object" && detail !== null ? detail.code : undefined;
  if (typeof code === "string" && OWN.test(code)) return code as AssistantCode;
  if (status === 0) return "network";
  if (status === 401) return code === "mfa_required" ? "mfaRequired" : "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 404) return "notFound";
  if (status === 409 && code === "proposal_hidden") return "hidden";
  return status === 503 ? "unavailable" : "failed";
}

type Answer = { data?: unknown; error?: unknown; response: Response };
type Call = (client: ApiClient) => Promise<Answer>;

/**
 * One call with the given client, or the typed client from the editor's save chunk. A thrown fetch (offline, or the
 * chunk failed to load) is "network".
 */
async function settle<T>(call: Call, client?: ApiClient): Promise<AssistantOutcome<T>> {
  try {
    const answer = await call(client ?? (await import("./save")).api);
    return answer.response.ok
      ? { ok: true, value: answer.data as T }
      : { ok: false, problem: assistantRefusal(answer.response.status, answer.error) };
  } catch {
    return { ok: false, problem: "network" };
  }
}

const CONSENT = "/api/me/proposals/{proposal_id}/assistant/consent";
const path = (id: string) => ({ params: { path: { proposal_id: id } } });

/** Whether the assistant is on for this sign-in, with the consent wording and its version to show. */
export function consentState(id: string, client?: ApiClient) {
  return settle<AssistantConsent>((api) => api.GET(CONSENT, path(id)), client);
}

/** Turns the assistant on for this sign-in, naming the version of the wording that was shown. */
export function grantConsent(id: string, version: string, client?: ApiClient) {
  return settle<AssistantConsent>((api) => api.POST(CONSENT, { ...path(id), body: { version } }), client);
}

/** Turns the assistant off for this sign-in. */
export function withdrawConsent(id: string, client?: ApiClient) {
  return settle<AssistantConsent>((api) => api.DELETE(CONSENT, path(id)), client);
}

/** One suggestion for the saved draft. The API never writes the proposal; neither does this. */
export function suggest(id: string, client?: ApiClient) {
  return settle<AssistantSuggestion>(
    (api) => api.POST("/api/me/proposals/{proposal_id}/assistant/suggestions", path(id)),
    client,
  );
}

/** What the panel calls (its tests pass fakes). */
export interface AssistantCalls {
  consentState: typeof consentState;
  grantConsent: typeof grantConsent;
  withdrawConsent: typeof withdrawConsent;
  suggest: typeof suggest;
}

/**
 * The answer's sentence key under ideaAssistant.status.*, or null when a new teaser is shown. `no_suggestion` also
 * covers each reason the API keeps to itself: nothing to improve, a suggestion the Tier-1 sanitiser refused, or one
 * that copied wording from the confidential fields (`rejected:tier2_overlap`).
 */
export function statusKey(answer: AssistantSuggestion) {
  if (answer.status !== "suggested") return answer.status;
  if (answer.teaser) return null;
  return answer.placement.length > 0 ? "hints_only" : "no_suggestion";
}
