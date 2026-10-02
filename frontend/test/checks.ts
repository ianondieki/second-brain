import { vi } from "vitest";

import {
  disclosure,
  overlap,
  type CheckOutcome,
  type ChecksCalls,
  type DisclosureCheck,
  type Originality,
} from "@/app/(app)/dev/ideas/checks";
import { createApiClient } from "@/lib/api/client";

import type { FakeAnswer } from "./assistant";

// Fixtures of the editor's teaser checks (REQ-PROP-04, REQ-REPO-01).

export const NONE: Originality = {
  band: "none",
  compared: 12,
  explanation: null,
  ai_drafted: false,
  demo_fallback: false,
  checked_at: "2026-10-02T07:30:00Z",
};

export const SOME: Originality = {
  ...NONE,
  band: "some_overlap",
  explanation: "Both describe booking shared cold storage by text message.",
  ai_drafted: true,
};

/** What the fake LLM gives for an overlap: the band, no sentence, labelled as the demo fallback. */
export const HIGH_DEMO: Originality = { ...NONE, band: "high_overlap", demo_fallback: true };

const VERSION_ID = "0199a000-0000-7000-8000-0000000000b1";

/** The rules' answer (bridge/proposals/disclosure.py RULES_WHY): the card words it itself. */
export const BY_RULES: DisclosureCheck = {
  flagged: true,
  fields: ["summary", "problem_statement"],
  why: "Server wording of the rules that the card never shows",
  source: "rules",
  ai_drafted: false,
  demo_fallback: false,
  version_id: VERSION_ID,
};

export const BY_MODEL: DisclosureCheck = {
  ...BY_RULES,
  fields: ["impact_claims"],
  why: "The impact field names the model and the training data.",
  source: "model",
  ai_drafted: true,
};

export const CLEAR: DisclosureCheck = { ...BY_RULES, flagged: false, fields: [], why: "Nothing", source: "model" };

/** The fake LLM's answer when the rules find nothing. */
export const DEMO_CLEAR: DisclosureCheck = { ...CLEAR, why: "Demo fallback: server words", source: "none", demo_fallback: true };

/** No answer (a suspected injection, a provider that is down): the API keeps the reason to itself. */
export const UNCHECKED: DisclosureCheck = { ...CLEAR, why: "Server words for a failed check", source: "none" };

const ok = <T>(value: T): CheckOutcome<T> => ({ ok: true, value });

/** Fake calls: no overlap, nothing given away, unless overridden. */
export function checksCalls(overrides: Partial<ChecksCalls> = {}) {
  return {
    overlap: vi.fn<ChecksCalls["overlap"]>(async () => ok(NONE)),
    disclosure: vi.fn<ChecksCalls["disclosure"]>(async () => ok(CLEAR)),
    ...overrides,
  };
}

/** The real calls over a fake network (as httpAssistant): each "METHOD path" answers from its queue. */
export function httpChecks(answers: Record<string, FakeAnswer[]>) {
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () => "bridge_csrf=test-token",
    set: () => {},
  });
  const seen: Array<{ method: string; path: string }> = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(String(input), "http://web.test"), init);
    const path = new URL(request.url).pathname;
    seen.push({ method: request.method, path });
    const next = answers[`${request.method} ${path}`]?.shift();
    if (!next) throw new Error(`unexpected ${request.method} ${path}`);
    if (next === "offline") throw new TypeError("Failed to fetch");
    const body = next.body === undefined ? "" : JSON.stringify(next.body);
    return new Response(body, { status: next.status, headers: { "Content-Type": "application/json" } });
  });
  const client = createApiClient({ baseUrl: "http://web.test", fetch: fetchImpl });
  const calls: ChecksCalls = {
    overlap: (id) => overlap(id, client),
    disclosure: (id) => disclosure(id, client),
  };
  return { calls, seen };
}
