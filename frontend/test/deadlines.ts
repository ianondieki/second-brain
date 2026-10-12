import type { Deadline } from "@/components/deadlines/month";
import type { Pipeline, PipelineItem } from "@/components/pipeline/data";

import { summary } from "./engagement";

/** A deadline as the API sends it (DeadlineOut): a stage deadline the other party acts on, unless overridden. */
export function deadline(overrides: Partial<Deadline> = {}): Deadline {
  const id = overrides.engagement_id ?? "0193f0c8-6a8f-7b4c-9d2e-3f4a5b6c7d8e";
  return {
    key: `stage:${id}`,
    kind: "stage",
    title: "Maziwa baridi",
    context: "Telco A",
    href: `/dev/engagements/${id}`,
    due_at: "2026-10-16T20:59:59.999Z",
    due_on: "2026-10-16",
    business_days_left: 4,
    overdue: false,
    mine: false,
    engagement_id: id,
    ...overrides,
  };
}

/** One card of the board (PipelineItem): an engagement under review, its window open, nobody assigned. */
export function pipelineItem(overrides: Partial<PipelineItem> = {}): PipelineItem {
  const base = summary();
  return {
    ...base,
    stage_entered_at: "2026-10-05T08:00:00Z",
    last_event_at: "2026-10-05T08:00:00Z",
    days_in_stage: 5,
    stalled: false,
    team: null,
    due: { due_on: "2026-10-16", business_days_left: 4, overdue: false, due_at: "2026-10-16T20:59:59.999Z" },
    ...overrides,
  } as PipelineItem;
}

/** A pipeline with the given cards per group (the rest empty) and a funnel. */
export function pipeline(
  items: Partial<Record<Pipeline["columns"][number]["group"], PipelineItem[]>> = {},
  funnel: Partial<Pipeline["funnel"]["entered"]> = {},
): Pipeline {
  const groups = ["review", "contact_nda", "agreement", "implementation", "close"] as const;
  return {
    columns: groups.map((group) => {
      const list = items[group] ?? [];
      return { group, count: list.length, median_days_in_stage: list.length ? 5 : null, items: list };
    }),
    funnel: {
      window_days: 90,
      entered: { review: 0, contact_nda: 0, agreement: 0, implementation: 0, close: 0, ...funnel },
      closed: 1,
      ended: 2,
    },
    stalled_after_bd: 5,
    now: "2026-10-10T06:36:00.000Z",
  };
}
