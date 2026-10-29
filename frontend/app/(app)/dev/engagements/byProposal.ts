import { awaitsMe, type Summary } from "@/components/tracker/model";

export interface ProposalGroup {
  proposalId: string;
  title: string;
  items: Summary[];
  /** At least one of its engagements waits on the developer. */
  needsYou: boolean;
}

/**
 * The developer's engagements grouped by proposal, one row per organisation (docs/spec/07 item 1): proposals with an
 * engagement waiting on the developer first; inside a proposal, the waiting ones first. Otherwise the API's order
 * (newest change first) is kept.
 */
export function byProposal(items: readonly Summary[]): ProposalGroup[] {
  const groups = new Map<string, ProposalGroup>();
  for (const item of items) {
    const group = groups.get(item.proposal_id) ?? {
      proposalId: item.proposal_id,
      title: item.proposal_title,
      items: [],
      needsYou: false,
    };
    group.items.push(item);
    group.needsYou ||= awaitsMe(item, "developer");
    groups.set(item.proposal_id, group);
  }
  const waitingFirst = <T,>(list: T[], waiting: (entry: T) => boolean) => [
    ...list.filter(waiting),
    ...list.filter((entry) => !waiting(entry)),
  ];
  return waitingFirst([...groups.values()], (group) => group.needsYou).map((group) => ({
    ...group,
    items: waitingFirst(group.items, (item) => awaitsMe(item, "developer")),
  }));
}
