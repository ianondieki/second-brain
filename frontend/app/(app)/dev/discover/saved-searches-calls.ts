import { api, type ApiClient } from "@/lib/api/client";

import { savedProblem, type SavedProblem, type SavedSearch, type SavedSearchIn } from "./saved-searches";

// The browser's saved-search calls (same-origin /api, CSRF header added by the client). Each settles into its value
// or a problem the panel words; a thrown fetch (offline, reset) is "network".

export type Outcome<T> = { ok: true; value: T } | { ok: false; problem: SavedProblem };

type Answer = { data?: unknown; error?: unknown; response: Response };

async function settle<T>(call: () => Promise<Answer>): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok) return { ok: true, value: data as T };
    return { ok: false, problem: savedProblem(response.status, error) };
  } catch {
    return { ok: false, problem: "network" };
  }
}

export interface SavedSearchCalls {
  save: (body: SavedSearchIn) => Promise<Outcome<SavedSearch>>;
  setAlerts: (id: string, alerts: boolean) => Promise<Outcome<SavedSearch>>;
  remove: (id: string) => Promise<Outcome<undefined>>;
}

export function savedSearchCalls(client: ApiClient = api): SavedSearchCalls {
  return {
    save: (body) => settle(() => client.POST("/api/me/saved-searches", { body })),
    setAlerts: (id, alerts) =>
      settle(() =>
        client.PATCH("/api/me/saved-searches/{search_id}", { params: { path: { search_id: id } }, body: { alerts } }),
      ),
    remove: (id) => settle(() => client.DELETE("/api/me/saved-searches/{search_id}", { params: { path: { search_id: id } } })),
  };
}
