import { api, type ApiClient } from "@/lib/api/client";

import {
  saveRefusal,
  type ConsentDecision,
  type ConsentItem,
  type PreferenceIn,
  type PreferenceItem,
  type SaveRefusal,
} from "./choices";

export type SaveOutcome = { ok: true; items: ConsentItem[] } | { ok: false; refusal: SaveRefusal };

/**
 * PUT /api/me/consents from the browser (same-origin /api; the client adds the CSRF header): the decisions, each on
 * the version whose wording was shown. Answers the person's consents as now recorded, or a refusal the page words; a
 * thrown fetch is "network".
 */
export async function saveChoices(
  decisions: Record<string, ConsentDecision>,
  client: ApiClient = api,
): Promise<SaveOutcome> {
  try {
    const { data, error, response } = await client.PUT("/api/me/consents", { body: decisions });
    if (response.ok && data) return { ok: true, items: data };
    return { ok: false, refusal: saveRefusal(response.status, error) };
  } catch {
    return { ok: false, refusal: "network" };
  }
}

export type PreferenceOutcome = { ok: true; items: PreferenceItem[] } | { ok: false; refusal: SaveRefusal };

/**
 * PUT /api/me/notification-preferences from the browser: one notification on or off (the preferences are their own
 * store, apart from the consents above; P21's saved-search digest is the first). Answers the person's preferences.
 */
export async function savePreference(body: PreferenceIn, client: ApiClient = api): Promise<PreferenceOutcome> {
  try {
    const { data, error, response } = await client.PUT("/api/me/notification-preferences", { body });
    if (response.ok && data) return { ok: true, items: data.items };
    return { ok: false, refusal: saveRefusal(response.status, error) };
  } catch {
    return { ok: false, refusal: "network" };
  }
}
