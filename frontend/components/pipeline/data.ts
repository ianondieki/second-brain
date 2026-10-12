import type { components } from "@/lib/api/schema";
import { forwardHeaders, serverApi } from "@/lib/api/server";
import { refused, type Read } from "@/components/tracker/data";

// The Board tab's read (P27 track B; REQ-ENG-14): GET /api/orgs/{org_id}/pipeline, bounded, the session forwarded.

export type Pipeline = components["schemas"]["PipelineOut"];
export type PipelineColumn = components["schemas"]["PipelineColumn"];
export type PipelineItem = components["schemas"]["PipelineItem"];
export type Group = PipelineColumn["group"];

export const GROUPS = ["review", "contact_nda", "agreement", "implementation", "close"] as const satisfies readonly Group[];

export async function readPipeline(orgId: string): Promise<Read<Pipeline>> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/pipeline", {
    params: { path: { org_id: orgId } },
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (data) return { ok: true, value: data };
  return { ok: false, refusal: refused(response.status, error, "GET /api/orgs/{org_id}/pipeline") };
}

/** Only the cards assigned to `userId` (the "Assigned to me" filter); the counts and medians become the filtered ones'. */
export function assignedTo(pipeline: Pipeline, userId: string): Pipeline {
  return {
    ...pipeline,
    columns: pipeline.columns.map((column) => {
      const items = column.items.filter((item) => item.team?.assignee?.user_id === userId);
      return { ...column, items, count: items.length, median_days_in_stage: median(items.map((i) => i.days_in_stage)) };
    }),
  };
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Whether any card carries the organisation's triage facts (the filter is offered only then). */
export function hasTeamFacts(pipeline: Pipeline): boolean {
  return pipeline.columns.some((column) => column.items.some((item) => item.team));
}
