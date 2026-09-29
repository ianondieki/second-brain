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
