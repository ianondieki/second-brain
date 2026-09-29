import type { MyProposalItem } from "./ideas";

// An idea's status as the owner reads it (server-rendered list and page; kept out of the editor's bundle).

/** What the owner sees: draft, published, held for review, not approved (a moderator refused it) or hidden. */
export type IdeaStatus = "draft" | "published" | "held" | "rejected" | "hidden";

export function ideaStatus(status: MyProposalItem["status"], moderation: MyProposalItem["moderation_state"]): IdeaStatus {
  if (status === "hidden" || status === "archived") return "hidden";
  if (status === "draft") return "draft";
  if (moderation === "held") return "held";
  if (moderation === "rejected") return "rejected";
  return "published";
}

/** A published idea with edits that are saved but not published yet (the list's second chip). */
export function hasUnpublishedChanges(item: Pick<MyProposalItem, "status" | "has_draft">): boolean {
  return item.status === "published" && item.has_draft;
}
