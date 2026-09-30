import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import { common } from "./outcomes";

// The submission assistant's calls (REQ-PROP-05; docs/spec/06 6.3, docs/spec/09). They load with the editor's
// assistant panel, when the owner opens it, never with the page. Each settles into its value or a problem the panel
// words with its own [[COPY-REVIEW]] string: the API's `message` and `detail.message` are never shown.

type Schemas = components["schemas"];
export type AssistantConsent = Schemas["AssistantConsentOut"];
export type AssistantSuggestion = Schemas["AssistantSuggestionOut"];
export type PlacementHint = Schemas["PlacementHintOut"];
export type SuggestedTeaser = Schemas["SuggestedTeaserOut"];

/** Why the assistant did not answer, as the panel words it (keys under ideaAssistant.problem.*). */
export type AssistantProblem =
  | "consentRequired"
  | "consentTextChanged"
  | "busy"
  | "dailyLimit"
  | "budget"
  | "paused"
  | "off"
  | "demoOnly"
  | "tier2Disabled"
  | "signedOut"
  | "mfaRequired"
  | "rateLimited"
  | "notFound"
  | "hidden"
  | "unavailable"
  | "network"
  | "failed";

export type AssistantOutcome<T> = { ok: true; value: T } | { ok: false; problem: AssistantProblem };

/** The assistant's own refusal codes (bridge/proposals/assistant.py, assistant_router.py, access.tier2_gate). */
const CODES: Record<string, AssistantProblem> = {
  consent_required: "consentRequired",
  consent_text_changed: "consentTextChanged",
  assistant_busy: "busy",
  assistant_rate_limited: "dailyLimit",
  assistant_budget: "budget",
  assistant_paused: "paused",
  assistant_off: "off",
  assistant_demo_only: "demoOnly",
  tier2_disabled: "tier2Disabled",
};

/** A refused assistant call: its own codes first (a 503 `assistant_off` is not a generic outage), then the shared ones. */
export function assistantRefusal(status: number, body: unknown): AssistantProblem {
  const code = apiErrorCode(body);
  const own = code !== undefined && Object.hasOwn(CODES, code) ? CODES[code] : undefined;
  if (own) return own;
  const shared = common(status, code);
  if (shared === "network" || shared === "signedOut" || shared === "mfaRequired") return shared;
  if (shared === "rateLimited" || shared === "notFound" || shared === "hidden" || shared === "unavailable") return shared;
  return "failed";
}

type Answer = { data?: unknown; error?: unknown; response: Response };

async function settle<T>(call: () => Promise<Answer>): Promise<AssistantOutcome<T>> {
  let answer: Answer;
  try {
    answer = await call();
  } catch {
    return { ok: false, problem: "network" };
  }
  if (answer.response.ok) return { ok: true, value: answer.data as T };
  return { ok: false, problem: assistantRefusal(answer.response.status, answer.error) };
}

const path = (id: string) => ({ params: { path: { proposal_id: id } } });

/** Whether the assistant is on for this sign-in, with the consent wording and its version to show. */
export function consentState(id: string, client: ApiClient = api) {
  return settle<AssistantConsent>(() => client.GET("/api/me/proposals/{proposal_id}/assistant/consent", path(id)));
}

/** Turns the assistant on for this sign-in, naming the version of the wording that was shown. */
export function grantConsent(id: string, version: string, client: ApiClient = api) {
  return settle<AssistantConsent>(() =>
    client.POST("/api/me/proposals/{proposal_id}/assistant/consent", { ...path(id), body: { version } }),
  );
}

/** Turns the assistant off for this sign-in. */
export function withdrawConsent(id: string, client: ApiClient = api) {
  return settle<AssistantConsent>(() => client.DELETE("/api/me/proposals/{proposal_id}/assistant/consent", path(id)));
}

/** One suggestion for the saved draft. The API never writes the proposal; neither does this. */
export function suggest(id: string, client: ApiClient = api) {
  return settle<AssistantSuggestion>(() =>
    client.POST("/api/me/proposals/{proposal_id}/assistant/suggestions", path(id)),
  );
}

/** What the panel calls (its tests pass fakes). */
export interface AssistantCalls {
  consentState: typeof consentState;
  grantConsent: typeof grantConsent;
  withdrawConsent: typeof withdrawConsent;
  suggest: typeof suggest;
}

/** The answer's message key under ideaAssistant.status.*, or null when there is something to show. */
export type StatusKey = "noSuggestion" | "demoFallback" | "injection" | "unavailable" | "hintsOnly";

/**
 * What to say about an answer. A suggestion with no new teaser but placement hints says so; every other status has
 * its fixed sentence. `no_suggestion` covers each reason the API keeps to itself (nothing to improve, a suggestion
 * the Tier-1 sanitiser refused, or one that copied wording from the confidential fields: `rejected:tier2_overlap`).
 */
export function statusKey(answer: AssistantSuggestion): StatusKey | null {
  switch (answer.status) {
    case "suggested":
      if (answer.teaser) return null;
      return answer.placement.length > 0 ? "hintsOnly" : "noSuggestion";
    case "demo_fallback":
      return "demoFallback";
    case "injection_suspected":
      return "injection";
    case "unavailable":
      return "unavailable";
    default:
      return "noSuggestion";
  }
}

