import { apiErrorCode } from "@/lib/api/error-code";

// The liked-niches picker's rules (REQ-PERS-03 through PUT /api/me/niches) and the profiling consent's toggle
// (PUT /api/me/consents), as pure functions the client components and the tests share.

/** Why a choice cannot be saved as it stands (checked before sending; the API checks again). */
export type CountIssue = "tooFew" | "tooMany";

export function countIssue(count: number, min: number, max: number): CountIssue | null {
  if (count < min) return "tooFew";
  if (count > max) return "tooMany";
  return null;
}

/** A refused save, as a fixed sentence's key under likedNiches.problem.* (the API's message is never shown). */
export type NichesProblem = "count" | "unknown" | "noProfile" | "signedOut" | "rateLimited" | "network" | "failed";

export function nichesRefusal(status: number, body: unknown): NichesProblem {
  const code = apiErrorCode(body);
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 404) return "noProfile";
  if (status === 422 && code === "liked_niches_count") return "count";
  if (status === 422 && code === "unknown_niche") return "unknown";
  return "failed";
}

/** A refused consent change, under likedNiches.profiling.problem.* */
export type ProfilingProblem = "changed" | "signedOut" | "rateLimited" | "network" | "failed";

export function profilingRefusal(status: number, body: unknown): ProfilingProblem {
  const code = apiErrorCode(body);
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 409 && code === "consent_text_changed") return "changed";
  return "failed";
}

/** Toggles one id in a list, keeping the list's order (a new id goes last). */
export function toggle(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
}

/** True when two lists hold the same ids, in any order. */
export function sameIds(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((id) => set.has(id));
}
