import { notFound, redirect } from "next/navigation";

import { apiErrorCode } from "@/lib/api/error-code";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { AdminNiche, Candidate, Run, Sources } from "./research";

// Server-side reads of the research admin API (REQ-RES-01; bridge/admin/research.py), each bounded so a hung API ends
// in the route's error page. The API admits a staff admin with a fresh second factor only: a 404 (no longer staff, or
// no two-step sign-in) is the console's not-found page, a stale second factor asks for a fresh code, and staff
// without the admin role are told the section is not theirs.

const TIMEOUT_MS = 5000;

export type Loaded<T> = { kind: "ok"; data: T } | { kind: "stepUp" } | { kind: "forbidden" };

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/** One answer as data, the step-up, or "forbidden"; the rest leaves the page (sign in, not found, error page). */
function settle<T>(what: string, { data, error, response }: { data?: T; error?: unknown; response: Response }) {
  if (data !== undefined) return { kind: "ok", data } as Loaded<T>;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) notFound();
  if (response.status === 403) {
    return (apiErrorCode(error) === "step_up_required" ? { kind: "stepUp" } : { kind: "forbidden" }) as Loaded<T>;
  }
  throw new Error(`${what} answered ${response.status}`);
}

/** Several reads as one: all their data, or the first step-up or refusal among them. */
function combine<T extends unknown[]>(...loaded: { [K in keyof T]: Loaded<T[K]> }): Loaded<T> {
  const refused = loaded.find((one) => one.kind !== "ok");
  if (refused) return refused as Loaded<T>;
  return { kind: "ok", data: loaded.map((one) => (one as { data: unknown }).data) as T };
}

export interface ResearchData {
  runs: Run[];
  candidates: Candidate[];
  sources: Sources;
  niches: AdminNiche[];
}

/** Everything the research page shows: runs (newest first), candidates, saved excerpts and niche labels. */
export async function getResearch(): Promise<Loaded<ResearchData>> {
  const api = serverApi();
  const [runs, candidates, sources, niches] = await Promise.all([
    api.GET("/api/admin/research/runs", await options()),
    api.GET("/api/admin/research/candidates", await options()),
    api.GET("/api/admin/research/sources", await options()),
    api.GET("/api/admin/niches", await options()),
  ]);
  const loaded = combine<[Run[], Candidate[], Sources, AdminNiche[]]>(
    settle("GET /api/admin/research/runs", { ...runs, data: runs.data?.items }),
    settle("GET /api/admin/research/candidates", { ...candidates, data: candidates.data?.items }),
    settle("GET /api/admin/research/sources", sources),
    settle("GET /api/admin/niches", niches),
  );
  if (loaded.kind !== "ok") return loaded;
  const [runList, candidateList, sourceList, nicheList] = loaded.data;
  return { kind: "ok", data: { runs: runList, candidates: candidateList, sources: sourceList, niches: nicheList } };
}

export interface ReviewData {
  /** Null when the card is no longer waiting for review (decided, or never a candidate). */
  candidate: Candidate | null;
  niches: AdminNiche[];
}

/** One candidate for review. The API lists candidates only, so the card is found in that list (at most 200). */
export async function getReview(problemId: string): Promise<Loaded<ReviewData>> {
  const api = serverApi();
  const [candidates, niches] = await Promise.all([
    api.GET("/api/admin/research/candidates", await options()),
    api.GET("/api/admin/niches", await options()),
  ]);
  const loaded = combine<[Candidate[], AdminNiche[]]>(
    settle("GET /api/admin/research/candidates", { ...candidates, data: candidates.data?.items }),
    settle("GET /api/admin/niches", niches),
  );
  if (loaded.kind !== "ok") return loaded;
  const [list, nicheList] = loaded.data;
  return { kind: "ok", data: { candidate: list.find((c) => c.id === problemId) ?? null, niches: nicheList } };
}
