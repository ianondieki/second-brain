import { redirect } from "next/navigation";
import { cache } from "react";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { ProblemDetail } from "./problem";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * A published problem card with its citations (GET /api/problems/{problem_id}; REQ-RES-02), or null when there is none
 * to show: a research candidate, a rejected or held card and an unknown id all answer 404 (AC-RES-2). Signed-in
 * people only (the API answers 401 otherwise). Cached per request: the title and the page share one call.
 */
export const getProblem = cache(async function getProblem(problemId: string): Promise<ProblemDetail | null> {
  if (!UUID.test(problemId)) return null;
  const { data, response } = await serverApi().GET("/api/problems/{problem_id}", {
    params: { path: { problem_id: problemId } },
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (data) return data;
  if (response.status === 404) return null;
  if (response.status === 401) redirect("/login");
  throw new Error(`GET /api/problems/{problem_id} answered ${response.status}`);
});
