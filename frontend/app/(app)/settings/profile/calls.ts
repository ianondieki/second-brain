import { profileRefusal, type Profile, type ProfileRefusal } from "@/app/(app)/dev/teams/teams";
import { api, type ApiClient } from "@/lib/api/client";
import { isRecord } from "@/lib/api/error-code";

// Settings › Profile from the browser (REQ-DEV-03): the profile's change (only the fields that changed: a county
// change counts toward the daily limit) and lifting a block. Each settles into what the screen says.

export interface ProfileChange {
  headline?: string | null;
  county_code?: string | null;
  peers_visible?: boolean;
  /** D3 (REQ-DEV-04): self-reported, shown on the certificates as such; null clears one. */
  github_login?: string | null;
  kecobo_number?: string | null;
  kipi_number?: string | null;
}

/** The self-reported references (D3), as PATCH /api/me/profile names them. */
export const REFERENCE_FIELDS = ["github_login", "kecobo_number", "kipi_number"] as const;
export type ReferenceField = (typeof REFERENCE_FIELDS)[number];

export type SaveOutcome =
  | { ok: true; profile: Profile }
  | { ok: false; refusal: ProfileRefusal; field?: ReferenceField };

export interface ProfileCalls {
  save: (change: ProfileChange) => Promise<SaveOutcome>;
  unblock: (userId: string) => Promise<boolean>;
}

export function profileCalls(client: ApiClient = api): ProfileCalls {
  return {
    async save(change) {
      try {
        const { data, error, response } = await client.PATCH("/api/me/profile", { body: change });
        if (data) return { ok: true, profile: data };
        const field = response.status === 422 ? refusedField(error) : undefined;
        return { ok: false, refusal: profileRefusal(response.status, error), ...(field ? { field } : {}) };
      } catch {
        return { ok: false, refusal: "failed" };
      }
    },
    async unblock(userId) {
      try {
        const { response } = await client.DELETE("/api/me/blocks/{user_id}", { params: { path: { user_id: userId } } });
        return response.ok;
      } catch {
        return false;
      }
    },
  };
}

/** The reference a request-validation error names (its `loc`), when it names one. */
export function refusedField(error: unknown): ReferenceField | undefined {
  const list = isRecord(error) && Array.isArray(error.detail) ? error.detail : [];
  for (const item of list) {
    const loc = isRecord(item) && Array.isArray(item.loc) ? item.loc : [];
    const field = REFERENCE_FIELDS.find((name) => loc.includes(name));
    if (field) return field;
  }
  return undefined;
}

/** What changed between the saved profile and the form, as the PATCH body (an empty headline clears it). */
export function profileChange(
  saved: Pick<Profile, "headline" | "county_code" | "peers_visible" | ReferenceField>,
  form: { headline: string; county: string; visible: boolean; references?: Partial<Record<ReferenceField, string>> },
): ProfileChange {
  const change: ProfileChange = {};
  for (const name of REFERENCE_FIELDS) {
    const typed = form.references?.[name];
    if (typed === undefined) continue;
    // A GitHub login typed with its "@" is the same login (the API drops one leading "@").
    const value = (name === "github_login" ? typed.trim().replace(/^@/, "") : typed.trim()) || null;
    if (value !== (saved[name] ?? null)) change[name] = value;
  }
  const headline = form.headline.trim() || null;
  if (headline !== (saved.headline ?? null)) change.headline = headline;
  const county = form.county || null;
  if (county !== (saved.county_code ?? null)) change.county_code = county;
  if (form.visible !== saved.peers_visible) change.peers_visible = form.visible;
  return change;
}
