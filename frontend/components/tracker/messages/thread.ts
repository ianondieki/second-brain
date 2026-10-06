import type { components } from "@/lib/api/schema";
import { formatDay, formatTime } from "@/lib/format";

// The engagement thread's pure parts (REQ-ENG-11, AC-TRACK-9; docs/spec/06 6.9 "Messages tab"): the API's shapes,
// the day groups the thread is drawn in, the files a person may attach, and the fixed sentence each refusal gets
// (`trackerMessages.*`; the API's own words are never shown). The browser loads this with the thread only.

type Schemas = components["schemas"];
export type Thread = Schemas["MessageThreadOut"];
/** A message as the thread draws it; `avatar`, when given, is what its avatar's initials come from (a team thread's
 * handle without its "dev-"). */
export type Message = Schemas["MessageOut"] & { avatar?: string };
export type SentFile = Schemas["MessageAttachmentOut"];
export type StagedFile = Schemas["StagedAttachmentOut"];
export type Limits = Schemas["ThreadLimits"];
export type ReportReason = Schemas["ReportBody"]["reasons"][number];

export const REPORT_REASONS = ["spam", "abuse", "contact_details", "confidential", "other"] as const satisfies readonly ReportReason[];

/** The composer shows its count from this many characters before the limit. */
export const METER_FROM = 400;

/** A day of the thread: its messages, oldest first, under one heading ("Today", "Yesterday", "2 Oct 2026"). */
export interface DayGroup {
  /** The day in Nairobi, "2026-10-05". */
  day: string;
  label: "today" | "yesterday" | null;
  /** The day as written when it is neither today nor yesterday. */
  date: string;
  messages: Message[];
}

/** A moment's calendar day in Nairobi ("2026-10-05"). */
export function nairobiDay(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date(iso));
}

function dayBefore(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/**
 * The messages in day groups, oldest first. `today` is the platform's day in Nairobi (the tracker's `today`), so a
 * moved demo clock and the server's render agree on what "Today" is.
 */
export function groupByDay(messages: readonly Message[], today: string, locale = "en"): DayGroup[] {
  const yesterday = dayBefore(today);
  const groups: DayGroup[] = [];
  for (const message of messages) {
    const day = nairobiDay(message.created_at);
    let group = groups.at(-1);
    if (!group || group.day !== day) {
      group = {
        day,
        label: day === today ? "today" : day === yesterday ? "yesterday" : null,
        date: formatDay(locale, message.created_at),
        messages: [],
      };
      groups.push(group);
    }
    group.messages.push(message);
  }
  return groups;
}

/** A message's time of day in Nairobi ("14:05"). */
export function messageTime(iso: string, locale = "en"): string {
  return formatTime(locale, iso);
}

/**
 * The first message by someone else that arrived after the caller last read the thread: the "New" line goes above
 * it. Null when there is none (or the caller never opened the thread and nothing is from others).
 */
export function firstUnread(messages: readonly Message[], lastReadAt: string | null): string | null {
  const read = lastReadAt ? Date.parse(lastReadAt) : -Infinity;
  return messages.find((m) => !m.mine && Date.parse(m.created_at) > read)?.id ?? null;
}

/** Older messages prepended to the ones shown, each once (a message posted meanwhile can fall on both pages). */
export function prependOlder(shown: readonly Message[], older: readonly Message[]): Message[] {
  const seen = new Set(shown.map((m) => m.id));
  return [...older.filter((m) => !seen.has(m.id)), ...shown];
}

/** A file size as people read it ("820 kB", "4.2 MB"), in the page's language. */
export function fileSize(bytes: number, locale = "en"): string {
  const [unit, value] = bytes >= 1_000_000 ? (["megabyte", bytes / 1_000_000] as const) : (["kilobyte", Math.max(1, bytes / 1000)] as const);
  return new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 1 }).format(value);
}

/** Megabytes in the "up to 20 MB" sentences (20,971,520 bytes reads as 20). */
export function maxMegabytes(limits: Limits): number {
  return Math.round(limits.max_attachment_bytes / (1024 * 1024));
}

export type FileProblem = "type" | "size" | "empty" | "infected" | "tooMany" | "staged" | "limit" | "storage" | "failed";

export type PostRefusal =
  | "blank"
  | "tooLong"
  | "invalid"
  | "containsContact"
  | "waitUploads"
  | "blockedFiles"
  | "pending"
  | "unknownFile"
  | "infected"
  | "expired"
  | "tooManyFiles"
  | "notOpen"
  | "readOnly"
  | "cannotPost"
  | "tooMany"
  | "conflict"
  | "network"
  | "attachFailed"
  | "generic";

/** Refusals that are about what was typed: said on the text box itself. */
export const TEXT_REFUSALS: ReadonlySet<PostRefusal> = new Set(["blank", "tooLong", "invalid", "containsContact"]);

/** Refusals after which the thread itself changed (it closed, or it is not open): the page is fetched again. */
export const REFRESH_REFUSALS: ReadonlySet<PostRefusal> = new Set(["readOnly", "notOpen", "cannotPost"]);

export type ReportRefusal = "reportOwn" | "reportLimit" | "reportFailed";

/**
 * The plural form of a count in the page's language ("one" or "other"; English and Swahili use only these). The
 * thread's strings are formatted for the browser without the ICU runtime (lib/i18n/client-strings.ts), so a sentence
 * with a count has one key per form, chosen here by Intl.PluralRules.
 */
export function pluralForm(count: number, locale = "en"): "one" | "other" {
  return new Intl.PluralRules(locale).select(count) === "one" ? "one" : "other";
}

/** The key of a post refusal's sentence: "refusal.tooMany.one" / ".other" by the minutes, else "refusal.<kind>". */
export function postRefusalKey(kind: PostRefusal, count: number, locale = "en") {
  return kind === "tooMany" ? (`refusal.tooMany.${pluralForm(count, locale)}` as const) : (`refusal.${kind}` as const);
}

/** The key of a file problem's sentence: "file.limit.one" / ".other" by the minutes, else "file.<problem>". */
export function fileProblemKey(problem: FileProblem, count: number, locale = "en") {
  return problem === "limit" ? (`file.limit.${pluralForm(count, locale)}` as const) : (`file.${problem}` as const);
}
