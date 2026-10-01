import { awaitsMe, type Summary } from "@/components/tracker/model";

/**
 * The developer Home's two engagement groups: "Needs you" (waiting on the developer) and the others, each in the
 * API's order (newest change first). An engagement waiting on the organisation alone is never "Needs you".
 */
export function homeGroups(items: readonly Summary[]): { waiting: Summary[]; others: Summary[] } {
  return {
    waiting: items.filter((item) => awaitsMe(item, "developer")),
    others: items.filter((item) => !awaitsMe(item, "developer")),
  };
}

import type { MyProposalItem } from "./ideas/ideas";
import { isFinished } from "@/components/tracker/model";

export interface HomeStats {
  /** Ideas the developer can still act on (hidden and archived ones are not counted). */
  ideas: number;
  published: number;
  /** Ideas not yet published (status draft); a published idea's saved edits are "unpublished changes", counted apart. */
  drafts: number;
  changes: number;
  engagements: number;
  active: number;
  /** The soonest deadline among the active engagements, and whose it is. */
  nextDue: Summary["due"];
  nextDueId: string | null;
}

/** The four figures of Home's stat tiles, from what the page already reads. */
export function homeStats(engagements: readonly Summary[], ideas: readonly MyProposalItem[]): HomeStats {
  const live = ideas.filter((idea) => idea.status !== "hidden" && idea.status !== "archived");
  const active = engagements.filter((item) => !isFinished(item.state));
  // The soonest deadline the developer owes comes first; with none owed, the soonest on any side.
  const byDue = (items: readonly Summary[]) => items.filter((item) => item.due).sort((a, b) => a.due!.due_on.localeCompare(b.due!.due_on));
  const owed = byDue(active.filter((item) => item.whose_turn.includes("developer")));
  const withDue = owed.length > 0 ? owed : byDue(active);
  return {
    ideas: live.length,
    published: live.filter((idea) => idea.status === "published").length,
    drafts: live.filter((idea) => idea.status === "draft").length,
    changes: live.filter((idea) => idea.status === "published" && idea.has_draft).length,
    engagements: engagements.length,
    active: active.length,
    nextDue: withDue[0]?.due ?? null,
    nextDueId: withDue[0]?.id ?? null,
  };
}
