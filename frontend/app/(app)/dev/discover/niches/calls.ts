import { api, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import { nichesRefusal, profilingRefusal, type NichesProblem, type ProfilingProblem } from "./picker";

// The browser's calls for the liked-niches page (same-origin /api through the Next.js rewrite, CSRF header added by
// the client). Each settles into its value or a problem the screen words; a thrown fetch (offline, reset) is
// "network".

type LikedNiches = components["schemas"]["LikedNichesOut"];
type ConsentItem = components["schemas"]["ConsentItem"];

export type SaveNichesOutcome = { ok: true; value: LikedNiches } | { ok: false; problem: NichesProblem };
export type ProfilingOutcome = { ok: true; value: ConsentItem } | { ok: false; problem: ProfilingProblem };

type Answer = { data?: unknown; error?: unknown; response: Response };

async function answer(call: () => Promise<Answer>): Promise<{ ok: boolean; status: number; body: unknown }> {
  try {
    const { data, error, response } = await call();
    return { ok: response.ok, status: response.status, body: response.ok ? data : error };
  } catch {
    return { ok: false, status: 0, body: undefined };
  }
}

/** Sets the whole list of liked niches (3 to 5 niche ids). */
export async function saveNiches(ids: string[], client: ApiClient = api): Promise<SaveNichesOutcome> {
  const result = await answer(() => client.PUT("/api/me/niches", { body: { liked: ids } }));
  if (result.ok && result.body) return { ok: true, value: result.body as LikedNiches };
  return { ok: false, problem: nichesRefusal(result.ok ? 500 : result.status, result.body) };
}

/** Records the profiling decision on the wording (version) the page showed. */
export async function setProfiling(granted: boolean, version: string, client: ApiClient = api): Promise<ProfilingOutcome> {
  const result = await answer(() => client.PUT("/api/me/consents", { body: { profiling: { granted, version } } }));
  const item = Array.isArray(result.body)
    ? (result.body as ConsentItem[]).find((consent) => consent.purpose === "profiling")
    : undefined;
  if (result.ok && item) return { ok: true, value: item };
  return { ok: false, problem: profilingRefusal(result.ok ? 500 : result.status, result.body) };
}
