import { vi } from "vitest";

import {
  consentState,
  grantConsent,
  suggest,
  withdrawConsent,
  type AssistantCalls,
  type AssistantConsent,
  type AssistantOutcome,
  type AssistantSuggestion,
} from "@/app/(app)/dev/ideas/assistant";
import { createApiClient } from "@/lib/api/client";

// Fixtures of the writing assistant's tests (REQ-PROP-05).

export const PROPOSAL_ID = "0199a000-0000-7000-8000-0000000000a1";

/** A stand-in for the API's consent wording (the real one lives in backend config/consents.yaml). */
export const CONSENT_OFF: AssistantConsent = {
  purpose: "tier2_llm_assistant",
  granted: false,
  scope: "this_session",
  text: "Fixture wording: during this sign-in only, let the writing assistant read my proposals when I ask.",
  version: "2026-09-29.2",
};
export const CONSENT_ON: AssistantConsent = { ...CONSENT_OFF, granted: true };

/** What the API's message would say; the panel must never show it. */
export const SERVER_MESSAGE = "Server wording that the screen never shows";

export const SUGGESTED: AssistantSuggestion = {
  status: "suggested",
  message: null,
  ai_drafted: true,
  demo_fallback: false,
  version_id: "0199a000-0000-7000-8000-0000000000b1",
  teaser: {
    title: "Shared solar chillers for dairy co-ops",
    summary: "Dairy co-ops book shared solar chillers by SMS, so evening milk stays fresh until collection.",
  },
  placement: [
    { field: "pricing", move: "to_tier1", reason: "A price per litre helps organisations judge the fit early." },
  ],
};

export const DEMO_FALLBACK: AssistantSuggestion = {
  status: "demo_fallback",
  message: SERVER_MESSAGE,
  ai_drafted: false,
  demo_fallback: true,
  version_id: SUGGESTED.version_id,
  teaser: null,
  placement: [],
};

const ok = <T>(value: T): AssistantOutcome<T> => ({ ok: true, value });

/** Fake calls: the assistant is off until granted, and every suggestion is SUGGESTED unless overridden. */
export function assistantCalls(overrides: Partial<AssistantCalls> = {}) {
  return {
    consentState: vi.fn<AssistantCalls["consentState"]>(async () => ok(CONSENT_OFF)),
    grantConsent: vi.fn<AssistantCalls["grantConsent"]>(async () => ok(CONSENT_ON)),
    withdrawConsent: vi.fn<AssistantCalls["withdrawConsent"]>(async () => ok(CONSENT_OFF)),
    suggest: vi.fn<AssistantCalls["suggest"]>(async () => ok(SUGGESTED)),
    ...overrides,
  };
}

export type FakeAnswer = { status: number; body?: unknown } | "offline";

/**
 * The real calls over a fake network: each "METHOD path" answers from its queue, so a test drives the panel with the
 * API's own status codes and bodies. A CSRF cookie is set, so state-changing calls go straight out.
 */
export function httpAssistant(answers: Record<string, FakeAnswer[]>) {
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () => "bridge_csrf=test-token",
    set: () => {},
  });
  const seen: Array<{ method: string; path: string; body: string }> = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(String(input), "http://web.test"), init);
    const path = new URL(request.url).pathname;
    seen.push({ method: request.method, path, body: await request.text() });
    const next = answers[`${request.method} ${path}`]?.shift();
    if (!next) throw new Error(`unexpected ${request.method} ${path}`);
    if (next === "offline") throw new TypeError("Failed to fetch");
    const body = next.body === undefined ? "" : JSON.stringify(next.body);
    return new Response(body, { status: next.status, headers: { "Content-Type": "application/json" } });
  });
  const client = createApiClient({ baseUrl: "http://web.test", fetch: fetchImpl });
  const calls: AssistantCalls = {
    consentState: (id) => consentState(id, client),
    grantConsent: (id, version) => grantConsent(id, version, client),
    withdrawConsent: (id) => withdrawConsent(id, client),
    suggest: (id) => suggest(id, client),
  };
  return { calls, seen };
}

/** The assistant routes of PROPOSAL_ID. */
export const ROUTE = {
  consent: `/api/me/proposals/${PROPOSAL_ID}/assistant/consent`,
  suggestions: `/api/me/proposals/${PROPOSAL_ID}/assistant/suggestions`,
};

/** An API error body, as bridge.errors.ApiError sends it. */
export function refusal(code: string) {
  return { detail: { code, message: SERVER_MESSAGE } };
}
