import type { Message, PostRefusal, Thread as EngagementThread } from "@/components/tracker/messages/thread";
import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The team thread in the shape the engagement thread's parts draw (REQ-DEV-03; components/tracker/messages), on its
// own so the thread's route bundles only this of team up's rules (docs/spec/07 item 5).

type TeamThread = components["schemas"]["ThreadOut"];
type TeamMessage = components["schemas"]["TeamMessageOut"];

/**
 * A team message in the engagement thread's shape (components/tracker/messages/Thread.tsx draws both): the other
 * developer by their handle (the avatar from what follows "dev-"), on the developer side, with no files.
 */
export function toMessage(message: TeamMessage, counterpart: string): Message {
  return {
    ...message,
    sender_name: message.mine ? "" : counterpart,
    // Handles read "dev-k61aq5tf": the avatar takes its initial from what follows "dev-".
    avatar: counterpart.replace(/^dev-/, ""),
    sender_party: "developer",
    attachments: [],
  };
}

/** The team thread's page in the engagement thread's shape: files off (max_attachments 0), its own length limit. */
export function toThreadPage(read: TeamThread, counterpart: string): EngagementThread {
  return {
    engagement_id: read.thread.id,
    status: read.thread.open ? "open" : "read_only",
    opens_at_stage: "INTEREST_CONFIRMED",
    can_post: read.can_post,
    unread: read.thread.unread,
    last_read_at: read.last_read_at,
    limits: { max_chars: read.max_chars ?? 4000, max_attachments: 0, max_attachment_bytes: 0, accepted_types: [] },
    items: read.items.map((message) => toMessage(message, counterpart)),
    next_cursor: read.next_cursor,
  };
}

/** A refused team message, as the composer words it (the thread closed: the page is read again). */
export function teamPostRefusal(status: number, error: unknown): PostRefusal {
  const code = apiErrorCode(error);
  if (code === "thread_closed") return "readOnly";
  if (code === "too_many_messages" || status === 429) return "tooMany";
  if (status === 404) return "cannotPost";
  if (status === 422) return "invalid";
  return "generic";
}
