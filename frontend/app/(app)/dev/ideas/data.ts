import { redirect } from "next/navigation";
import { cache } from "react";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import {
  type AttestationText,
  type County,
  type MyProposal,
  type MyProposalItem,
  type NicheNode,
  type ProblemCard,
  type ProblemRef,
} from "./ideas";
import type { Originality } from "./checks";
import { isProposalId } from "./routes";

// Server-side calls for the My ideas screens (signed in only). Each call is bounded, so a hung API ends in the
// route's error page instead of a page that never renders.
const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

function failed(path: string, status: number): never {
  // The session ended between the page's /me check and this call: sign in again.
  if (status === 401) redirect("/login");
  throw new Error(`${path} answered ${status}`);
}

/** Your ideas, newest change first (GET /api/me/proposals). */
export async function myIdeas(): Promise<MyProposalItem[]> {
  const { data, response } = await serverApi().GET("/api/me/proposals", await options());
  if (!data) failed("GET /api/me/proposals", response.status);
  return data.items;
}

/**
 * One of your ideas with its current and draft versions and your own Tier 2 (the API audits the read), or null when
 * the id is not one of yours. Cached per request, so the title and the page share one call.
 */
export const myIdea = cache(async function myIdea(id: string): Promise<MyProposal | null> {
  if (!isProposalId(id)) return null;
  const { data, response } = await serverApi().GET("/api/me/proposals/{proposal_id}", {
    params: { path: { proposal_id: id } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 404) return null;
  return failed("GET /api/me/proposals/{proposal_id}", response.status);
});

export interface EditorOptions {
  niches: NicheNode[];
  counties: County[];
  attestations: AttestationText;
  problems: ProblemCard[];
}

/** What the editor's selects, picker and final step need, fetched together. */
export async function editorOptions(): Promise<EditorOptions> {
  const api = serverApi();
  const [niches, filters, attestations, problems] = await Promise.all([
    api.GET("/api/directory/niches", await options()),
    api.GET("/api/directory/filter-options", await options()),
    api.GET("/api/proposals/attestations", await options()),
    api.GET("/api/problems", { params: { query: { limit: 20 } }, ...(await options()) }),
  ]);
  if (!niches.data) failed("GET /api/directory/niches", niches.response.status);
  if (!filters.data) failed("GET /api/directory/filter-options", filters.response.status);
  if (!attestations.data) failed("GET /api/proposals/attestations", attestations.response.status);
  if (!problems.data) failed("GET /api/problems", problems.response.status);
  return {
    niches: niches.data,
    counties: filters.data.counties,
    attestations: attestations.data,
    problems: problems.data.items,
  };
}

/**
 * A published problem a new idea can link, as the editor holds linked problems, or null when it cannot be linked: an
 * id that is not a uuid (never fetched), one the API does not show (a candidate, a held or rejected card and an
 * unknown id all answer 404; 422 for a malformed one), or an API that fails or does not answer in time. The editor
 * then opens empty, as without `?problem=`. Only a lost session (401) leaves the page, to sign in again.
 */
export async function linkableProblem(problemId: string): Promise<ProblemRef | null> {
  if (!isProposalId(problemId)) return null; // the same uuid shape
  let answer;
  try {
    answer = await serverApi().GET("/api/problems/{problem_id}", {
      params: { path: { problem_id: problemId } },
      ...(await options()),
    });
  } catch {
    return null; // timeout or network: the idea starts without the problem
  }
  const { data, response } = answer;
  if (data) {
    const { id, title, source, label, niche, seeded_example, published_at } = data;
    return { id, title, source, label, niche, seeded_example, published_at };
  }
  if (response.status === 401) redirect("/login");
  return null;
}

/**
 * Today's last overlap check of one of your ideas (GET /api/me/proposals/{id}/originality, REQ-PROP-04), so the
 * editor shows it again after a reload; null when there is none today. Best effort: any refusal, a timeout or a lost
 * connection leaves the editor without it (the check can simply be run again).
 */
export async function lastOverlap(id: string): Promise<Originality | null> {
  if (!isProposalId(id)) return null;
  try {
    const { data } = await serverApi().GET("/api/me/proposals/{proposal_id}/originality", {
      params: { path: { proposal_id: id } },
      ...(await options()),
    });
    return data ?? null;
  } catch {
    return null;
  }
}

/** A county's name by its code (KE-30 → Nairobi City), or the code when the list cannot be read. */
export async function countyName(code: string): Promise<string> {
  const { data } = await serverApi().GET("/api/directory/filter-options", await options());
  return data?.counties.find((county) => county.code === code)?.name ?? code;
}
