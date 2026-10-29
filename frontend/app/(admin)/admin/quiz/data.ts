import { serverApi } from "@/lib/api/server";

import { readOptions as options, settle, type Loaded } from "../load";
import type { QuizSetDetail, QuizSetSummary } from "./quiz";

// Server-side reads of the staff quiz API (REQ-DEV-01; /api/admin/quiz/*) through the console's shared loader
// (../load.ts): the API admits a staff admin with a fresh second factor only.

/** Every set the queue lists (draft, approved and rejected; at most 200). */
export async function getQuizSets(): Promise<Loaded<QuizSetSummary[]>> {
  const answer = await serverApi().GET("/api/admin/quiz/sets", { params: { query: { limit: 200 } }, ...(await options()) });
  return settle("GET /api/admin/quiz/sets", { ...answer, data: answer.data?.items });
}

/** One set with its questions, flags and plays; null when there is no such set (404). */
export async function getQuizSet(setId: string): Promise<Loaded<QuizSetDetail | null>> {
  const answer = await serverApi().GET("/api/admin/quiz/sets/{set_id}", {
    params: { path: { set_id: setId } },
    ...(await options()),
  });
  if (answer.response.status === 404) return { kind: "ok", data: null };
  return settle("GET /api/admin/quiz/sets/{set_id}", answer);
}
