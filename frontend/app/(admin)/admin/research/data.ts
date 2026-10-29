import { serverApi } from "@/lib/api/server";

import { combine, readOptions as options, settle, type Loaded } from "../load";
import type { AdminNiche, Candidate, Run, Sources } from "./research";
import type { TrendCandidate, TrendCardDetail } from "./trends/trends";

// Server-side reads of the research admin API (REQ-RES-01; bridge/admin/research.py) through the console's shared
// loader (../load.ts): the API admits a staff admin with a fresh second factor only.

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

/** The trend cards waiting for review (REQ-DEV-02), newest first. */
export async function getTrendCandidates(): Promise<Loaded<TrendCandidate[]>> {
  const answer = await serverApi().GET("/api/admin/research/trends", {
    params: { query: { status: "candidate", limit: 50 } },
    ...(await options()),
  });
  return settle("GET /api/admin/research/trends", { ...answer, data: answer.data?.items });
}

/** One trend card with its sources; null when there is none with that id (404). */
export async function getTrendCard(cardId: string): Promise<Loaded<TrendCardDetail | null>> {
  const answer = await serverApi().GET("/api/admin/research/trends/{card_id}", {
    params: { path: { card_id: cardId } },
    ...(await options()),
  });
  if (answer.response.status === 404) return { kind: "ok", data: null };
  return settle("GET /api/admin/research/trends/{card_id}", answer);
}
