import { api, type ApiClient } from "@/lib/api/client";

import { draftBody } from "./draft";
import type { DraftBody, EditorState, MyProposal } from "./ideas";
import { saveRefusal, type Refusal, type SaveProblem } from "./outcomes";

// Saving a draft: the only call the editor needs on the first edit, so it loads on its own (docs/spec/07 item 5).
// The other calls are in calls.ts, which re-exports these.

export type Outcome<T, P extends string> = { ok: true; value: T } | ({ ok: false } & Refusal<P>);

type Answer = { data?: unknown; error?: unknown; response: Response };

export async function settle<T, P extends string>(
  call: () => Promise<Answer>,
  refuse: (status: number, body: unknown) => Refusal<P>,
): Promise<Outcome<T, P>> {
  let answer: Answer;
  try {
    answer = await call();
  } catch {
    return { ok: false, ...refuse(0, undefined) };
  }
  if (answer.response.ok) return { ok: true, value: answer.data as T };
  return { ok: false, ...refuse(answer.response.status, answer.error) };
}

/** Save the draft: a new proposal (POST) the first time, then PATCH. */
export function saveDraft(id: string | null, body: DraftBody, client: ApiClient = api) {
  return settle<MyProposal, SaveProblem>(
    () =>
      id
        ? client.PATCH("/api/me/proposals/{proposal_id}", { params: { path: { proposal_id: id } }, body })
        : client.POST("/api/me/proposals", { body }),
    saveRefusal,
  );
}

/** Save everything the editor holds; `held` names the parts left out as typed (links, a half-written problem). */
export async function saveState(id: string | null, state: EditorState, client: ApiClient = api) {
  const plan = draftBody(state);
  return { outcome: await saveDraft(id, plan.body, client), held: plan.held };
}

