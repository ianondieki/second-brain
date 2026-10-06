import { profileRefusal, type Profile, type ProfileRefusal } from "@/app/(app)/dev/teams/teams";
import { api, type ApiClient } from "@/lib/api/client";

// Settings › Profile from the browser (REQ-DEV-03): the profile's change (only the fields that changed: a county
// change counts toward the daily limit) and lifting a block. Each settles into what the screen says.

export interface ProfileChange {
  headline?: string | null;
  county_code?: string | null;
  peers_visible?: boolean;
}

export interface ProfileCalls {
  save: (change: ProfileChange) => Promise<{ ok: true; profile: Profile } | { ok: false; refusal: ProfileRefusal }>;
  unblock: (userId: string) => Promise<boolean>;
}

export function profileCalls(client: ApiClient = api): ProfileCalls {
  return {
    async save(change) {
      try {
        const { data, error, response } = await client.PATCH("/api/me/profile", { body: change });
        return data ? { ok: true, profile: data } : { ok: false, refusal: profileRefusal(response.status, error) };
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

/** What changed between the saved profile and the form, as the PATCH body (an empty headline clears it). */
export function profileChange(saved: Pick<Profile, "headline" | "county_code" | "peers_visible">, form: { headline: string; county: string; visible: boolean }): ProfileChange {
  const change: ProfileChange = {};
  const headline = form.headline.trim() || null;
  if (headline !== (saved.headline ?? null)) change.headline = headline;
  const county = form.county || null;
  if (county !== (saved.county_code ?? null)) change.county_code = county;
  if (form.visible !== saved.peers_visible) change.peers_visible = form.visible;
  return change;
}
