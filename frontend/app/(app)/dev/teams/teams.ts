import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import type { Message, PostRefusal, Thread as EngagementThread } from "@/components/tracker/messages/thread";

// Peers and team up's pure parts (REQ-DEV-03; D-58, D-62; docs/platform/tasks/P22.md section C): the API's shapes, the
// addresses, the order the lists are drawn in, which sentence each refusal gets, and the team thread in the shape the
// engagement thread's parts draw (components/tracker/messages). The API decides who sees whom; this only words it.

type Schemas = components["schemas"];
export type Peer = Schemas["PeerOut"];
export type PeersPage = Schemas["PeersPage"];
export type Invitation = Schemas["InvitationOut"];
export type Invitations = Schemas["InvitationsOut"];
export type ThreadSummary = Schemas["ThreadSummaryOut"];
export type TeamThread = Schemas["ThreadOut"];
export type TeamMessage = Schemas["TeamMessageOut"];
export type Contribution = Schemas["ContributionOut"];
export type Blocked = Schemas["BlockedOut"];
export type Profile = Schemas["ProfileOut"];
export type ProblemCard = Schemas["ProblemCard"];

export const PEERS_PATH = "/dev/peers";
export const TEAMS_PATH = "/dev/teams";
export const PROFILE_SETTINGS_PATH = "/settings/profile";
/** Peers a page (the API's default and maximum) and on Home (a first page of three is not counted by the API). */
export const PEERS_PER_PAGE = 20;
export const HOME_PEERS = 3;
/** An invitation's note: at most 300 characters (bridge/teams/text.py). */
export const NOTE_MAX = 300;
/** A headline: at most 160 characters (ProfileUpdate). */
export const HEADLINE_MAX = 160;

export function threadHref(id: string): string {
  return `${TEAMS_PATH}/${encodeURIComponent(id)}`;
}

/** Characters as people count them (an emoji is one), the way the API counts a note. */
export function charCount(text: string): number {
  return Array.from(text).length;
}

/** A peer's niches by name, in the API's order; a slug the niche list does not know is left out. */
export function nicheNames(slugs: readonly string[], names: Readonly<Record<string, string>>): string[] {
  return slugs.flatMap((slug) => (names[slug] ? [names[slug]] : []));
}

/** Open threads first, then closed ones; each group by its latest message (or opening), newest first. */
export function sortThreads<T extends Pick<ThreadSummary, "open" | "last_message_at" | "created_at">>(threads: readonly T[]): T[] {
  const at = (thread: T) => Date.parse(thread.last_message_at ?? thread.created_at);
  return [...threads].sort((a, b) => Number(b.open) - Number(a.open) || at(b) - at(a));
}

/** Why a closed thread is closed, as its sentence's key (a thread closed for no stated reason reads as ended). */
export function closedReason(thread: Pick<ThreadSummary, "open" | "closed_reason">): "left" | "blocked" | "ended" | null {
  if (thread.open) return null;
  return thread.closed_reason ?? "ended";
}

/**
 * A team message in the engagement thread's shape (components/tracker/messages/Thread.tsx draws both): the other
 * developer by their handle, on the developer side, with no files (a team message has none).
 */
export function toMessage(message: TeamMessage, counterpart: string): Message {
  return {
    ...message,
    sender_name: message.mine ? "" : counterpart,
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

export type InviteRefusal =
  | "peersOff"
  | "peerUnavailable"
  | "problemUnavailable"
  | "alreadyInvited"
  | "tooMany"
  | "noteTooLong"
  | "invalid"
  | "failed";

const INVITE_CODES: Record<string, InviteRefusal> = {
  peers_off: "peersOff",
  peer_unavailable: "peerUnavailable",
  problem_unavailable: "problemUnavailable",
  already_invited: "alreadyInvited",
  too_many_invitations: "tooMany",
};

export function inviteRefusal(status: number, error: unknown): InviteRefusal {
  const code = apiErrorCode(error);
  if (code && code in INVITE_CODES) return INVITE_CODES[code];
  if (status === 429) return "tooMany";
  if (status === 422) return "invalid";
  return "failed";
}

/** An invitation's answer refused: already answered or withdrawn (409, or gone: 404), or anything else. */
export function decideRefusal(status: number): "gone" | "failed" {
  return status === 409 || status === 404 ? "gone" : "failed";
}

export type CreditRefusal = "already" | "notCounterpart" | "failed";

export function creditRefusal(status: number, error: unknown): CreditRefusal {
  const code = apiErrorCode(error);
  if (code === "already_contributor" || status === 409) return "already";
  if (code === "not_a_counterpart") return "notCounterpart";
  return "failed";
}

export type ProfileRefusal = "tooMany" | "invalid" | "signedOut" | "failed";

export function profileRefusal(status: number, error: unknown): ProfileRefusal {
  if (apiErrorCode(error) === "too_many_profile_changes" || status === 429) return "tooMany";
  if (status === 422) return "invalid";
  if (status === 401) return "signedOut";
  return "failed";
}

/** The plural form of a count for the strings formatted without the ICU runtime ("one" or "other"). */
export function pluralForm(count: number, locale = "en"): "one" | "other" {
  return new Intl.PluralRules(locale).select(count) === "one" ? "one" : "other";
}

/** A list of names as the language joins them ("a, b and c"; "a, b na c"). */
export function nameList(names: readonly string[], locale = "en"): string {
  return new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(names);
}
