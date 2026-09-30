import { serverApi } from "@/lib/api/server";

import { readOptions, settle, type Loaded } from "../load";
import type { Case, ModerationView } from "./moderation";

// Server-side reads of the moderation queue (REQ-MOD-01; GET /api/admin/moderation/cases and one case by id,
// bridge/admin/moderation.py): staff admins and moderators with a fresh second factor.

/** One view of the queue: the open cases oldest first, or the decided ones newest decision first (at most 200). */
export async function getQueue(view: ModerationView): Promise<Loaded<Case[]>> {
  const { data, error, response } = await serverApi().GET("/api/admin/moderation/cases", {
    ...(await readOptions()),
    params: { query: { decided: view === "decided" } },
  });
  return settle("GET /api/admin/moderation/cases", { data: data?.items, error, response });
}

export interface CaseView {
  /** Null when there is no such case. */
  item: Case | null;
  /** The oldest other open case this moderator can decide: where "Review the next case" goes. */
  nextId: string | null;
}

/**
 * One case, open or decided, wherever it falls in the queue (GET /api/admin/moderation/cases/{case_id}; the lists stop
 * at 200), and the next one to review from the open list. Both are read at once; the list's answer settles access
 * (sign-in, not found, step-up, refusal), so a 404 for the case itself means only that there is no such case.
 */
export async function getCase(caseId: string): Promise<Loaded<CaseView>> {
  const [one, open] = await Promise.all([readCase(caseId), getQueue("open")]);
  if (open.kind !== "ok") return open;
  const nextId = open.data.find((other) => other.id !== caseId && other.actions.length > 0)?.id ?? null;
  if (one.response.status === 404) return { kind: "ok", data: { item: null, nextId } };
  const found = settle("GET /api/admin/moderation/cases/{case_id}", one);
  if (found.kind !== "ok") return found;
  return { kind: "ok", data: { item: found.data, nextId } };
}

async function readCase(caseId: string) {
  const { data, error, response } = await serverApi().GET("/api/admin/moderation/cases/{case_id}", {
    ...(await readOptions()),
    params: { path: { case_id: caseId } },
  });
  return { data, error, response };
}
