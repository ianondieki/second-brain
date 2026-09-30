import { serverApi } from "@/lib/api/server";

import { readOptions, settle, type Loaded } from "../load";
import type { Case, ModerationView } from "./moderation";

// Server-side reads of the moderation queue (REQ-MOD-01; GET /api/admin/moderation/cases, bridge/admin/moderation.py):
// staff admins and moderators with a fresh second factor.

/** One view of the queue: the open cases oldest first, or the decided ones newest decision first (at most 200). */
export async function getQueue(view: ModerationView): Promise<Loaded<Case[]>> {
  const { data, error, response } = await serverApi().GET("/api/admin/moderation/cases", {
    ...(await readOptions()),
    params: { query: { decided: view === "decided" } },
  });
  return settle("GET /api/admin/moderation/cases", { data: data?.items, error, response });
}

export interface CaseView {
  /** Null when the case is in neither list (unknown, or decided and past the list's end). */
  item: Case | null;
  /** The oldest other open case this moderator can decide: where "Review the next case" goes. */
  nextId: string | null;
}

/**
 * One case and the next one to review. The API lists cases only, so the case is found among the open ones, then among
 * the decided ones (each list at most 200).
 */
export async function getCase(caseId: string): Promise<Loaded<CaseView>> {
  const open = await getQueue("open");
  if (open.kind !== "ok") return open;
  const nextId = open.data.find((other) => other.id !== caseId && other.actions.length > 0)?.id ?? null;
  const found = open.data.find((other) => other.id === caseId);
  if (found) return { kind: "ok", data: { item: found, nextId } };
  const decided = await getQueue("decided");
  if (decided.kind !== "ok") return decided;
  return { kind: "ok", data: { item: decided.data.find((other) => other.id === caseId) ?? null, nextId } };
}
