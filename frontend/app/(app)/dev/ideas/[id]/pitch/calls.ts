import { api, type ApiClient } from "@/lib/api/client";

import type { PitchResult, TagOut } from "./picker";
import { pitchRefusal, withdrawRefusal, type PitchRefusal, type WithdrawProblem } from "./refusals";

// The browser's calls for pitching and withdrawing (same-origin /api through the Next.js rewrite, CSRF header added
// by the client). Each settles into its value or a refusal the screen words; a thrown fetch (offline, reset) is
// "network".

export type PitchOutcome = { ok: true; value: PitchResult } | ({ ok: false } & PitchRefusal);
export type WithdrawOutcome = { ok: true; value: TagOut } | { ok: false; problem: WithdrawProblem };

type Answer = { data?: unknown; error?: unknown; response: Response };

async function answer(call: () => Promise<Answer>): Promise<{ ok: boolean; status: number; body: unknown }> {
  try {
    const { data, error, response } = await call();
    return { ok: response.ok, status: response.status, body: response.ok ? data : error };
  } catch {
    return { ok: false, status: 0, body: undefined };
  }
}

/** Pitch the proposal to these organisations (1 to 20; one transaction: all of them, or none). */
export async function pitch(proposalId: string, orgIds: string[], client: ApiClient = api): Promise<PitchOutcome> {
  const result = await answer(() =>
    client.POST("/api/me/proposals/{proposal_id}/tags", {
      params: { path: { proposal_id: proposalId } },
      body: { org_ids: orgIds },
    }),
  );
  if (result.ok && result.body) return { ok: true, value: result.body as PitchResult };
  return { ok: false, ...pitchRefusal(result.ok ? 500 : result.status, result.body) };
}

/** Withdraw an open held tag (it closes; the organisation never saw it). */
export async function withdrawTag(proposalId: string, tagId: string, client: ApiClient = api): Promise<WithdrawOutcome> {
  const result = await answer(() =>
    client.POST("/api/me/proposals/{proposal_id}/tags/{tag_id}/withdraw", {
      params: { path: { proposal_id: proposalId, tag_id: tagId } },
    }),
  );
  if (result.ok && result.body) return { ok: true, value: result.body as TagOut };
  return { ok: false, problem: withdrawRefusal(result.ok ? 500 : result.status, result.body) };
}
