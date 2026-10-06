import { apiErrorCode, detailOf, isRecord } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The event form's plain logic (REQ-DEV-02; D-60; P22 card B default (1)), shared by an organisation's "Post an
// event" and the staff's "Post a platform event": the draft and its checks, the body it sends (times in Nairobi,
// which keeps +03:00 all year), and the refusals it words. The API decides; this only words it (bridge/events/text.py).

type Schemas = components["schemas"];
export type EventOut = Schemas["EventOut"];
export type EventBody = Schemas["EventIn"];
export type EventStatus = EventOut["status"];

/** The stored bounds the API checks (bridge/events/models.py). */
export const EVENT_LIMITS = { title: 120, description: 1000, venue: 160 } as const;
/** An event lasts at most three days (P22 card B default (3)). */
export const MAX_SPAN_MS = 3 * 24 * 60 * 60 * 1000;
const NAIROBI_OFFSET = "+03:00";

export interface EventDraft {
  title: string;
  description: string;
  /** "YYYY-MM-DD" and "HH:MM", Nairobi time. */
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
  online: boolean;
  venue: string;
  /** A county code ("KE-30"), or "" before one is chosen. */
  county: string;
  joinUrl: string;
  link: string;
}

export const EMPTY_EVENT: EventDraft = {
  title: "",
  description: "",
  startDate: "",
  startTime: "",
  endDate: "",
  endTime: "",
  online: false,
  venue: "",
  county: "",
  joinUrl: "",
  link: "",
};

/** The form's fields in the order the page shows them (the first with a problem takes focus). */
export const EVENT_FIELDS = ["title", "description", "startDate", "startTime", "endDate", "endTime", "venue", "county", "joinUrl", "link"] as const;
export type EventField = (typeof EVENT_FIELDS)[number];

/** A field's problem, worded under `eventForm.fieldError.*` (the API's codes, and the form's own "missing"). */
export const FIELD_CODES = [
  "blank",
  "too_long",
  "control_character",
  "invalid_url",
  "unknown_county",
  "start_past",
  "end_before_start",
  "span_too_long",
  "join_url_required",
  "venue_required",
  "county_required",
  "online_has_place",
  "venue_has_join_url",
  "other",
] as const;
export type FieldCode = (typeof FIELD_CODES)[number];
export type EventErrors = Partial<Record<EventField, FieldCode>>;

/** Characters as the API counts them (code points, after trimming). */
export function charCount(text: string): number {
  return Array.from(text.trim()).length;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TIME = /^\d{2}:\d{2}$/;

/** A Nairobi date and time as the API's ISO 8601 with its offset, or null when either is not filled in. */
export function nairobiIso(date: string, time: string): string | null {
  return DAY.test(date) && TIME.test(time) ? `${date}T${time}:00${NAIROBI_OFFSET}` : null;
}

function httpsAddress(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" && !!url.hostname && !url.username && !url.password;
  } catch {
    return false;
  }
}

/** What must be fixed before the form is sent (the API checks everything again, the start against its clock too). */
export function checkEvent(draft: EventDraft): EventErrors {
  const errors: EventErrors = {};
  const text = (field: "title" | "description" | "venue", limit: number) => {
    if (!draft[field].trim()) errors[field] = "blank";
    else if (charCount(draft[field]) > limit) errors[field] = "too_long";
  };
  text("title", EVENT_LIMITS.title);
  text("description", EVENT_LIMITS.description);
  if (!DAY.test(draft.startDate)) errors.startDate = "blank";
  if (!TIME.test(draft.startTime)) errors.startTime = "blank";
  if (!DAY.test(draft.endDate)) errors.endDate = "blank";
  if (!TIME.test(draft.endTime)) errors.endTime = "blank";
  const start = nairobiIso(draft.startDate, draft.startTime);
  const end = nairobiIso(draft.endDate, draft.endTime);
  if (start && end) {
    const span = Date.parse(end) - Date.parse(start);
    if (span <= 0) errors.endDate = "end_before_start";
    else if (span > MAX_SPAN_MS) errors.endDate = "span_too_long";
  }
  if (draft.online) {
    if (!draft.joinUrl.trim()) errors.joinUrl = "join_url_required";
    else if (!httpsAddress(draft.joinUrl)) errors.joinUrl = "invalid_url";
  } else {
    if (!draft.venue.trim()) errors.venue = "venue_required";
    else if (charCount(draft.venue) > EVENT_LIMITS.venue) errors.venue = "too_long";
    if (!draft.county) errors.county = "county_required";
  }
  if (draft.link.trim() && !httpsAddress(draft.link)) errors.link = "invalid_url";
  return errors;
}

/** The API's EventIn: an online event sends its join address and no place; one at a venue the opposite. */
export function eventBody(draft: EventDraft): EventBody {
  const link = draft.link.trim();
  return {
    title: draft.title.trim(),
    description: draft.description.trim(),
    starts_at: nairobiIso(draft.startDate, draft.startTime) ?? "",
    ends_at: nairobiIso(draft.endDate, draft.endTime) ?? "",
    online: draft.online,
    venue: draft.online ? null : draft.venue.trim(),
    county_code: draft.online ? null : draft.county || null,
    join_url: draft.online ? draft.joinUrl.trim() : null,
    link: link || null,
  };
}

// ------------------------------------------------------------------------------------------------ refusals

/** Why an event was not posted, decided or cancelled (`eventForm.refusal.*`). */
export type EventRefusal =
  | "verification"
  | "orgUnavailable"
  | "notPoster"
  | "dailyLimit"
  | "invalid"
  | "notCancellable"
  | "alreadyDecided"
  | "changedSinceReview"
  | "eventOver"
  | "organisationUnavailable"
  | "stepUp"
  | "mfaSetup"
  | "mfaCode"
  | "notFound"
  | "forbidden"
  | "signedOut"
  | "network"
  | "generic";

/** One field the API refused, by the form's name for it (never the refused text). */
export interface FieldIssue {
  field: EventField;
  code: FieldCode;
}

export interface EventRefused {
  ok: false;
  refusal: EventRefusal;
  /** A 422 invalid_event's fields, each with its code. */
  fields: FieldIssue[];
}

const API_FIELDS: Record<string, EventField> = {
  title: "title",
  description: "description",
  starts_at: "startDate",
  ends_at: "endDate",
  venue: "venue",
  county_code: "county",
  join_url: "joinUrl",
  link: "link",
};

const CODES: Record<string, EventRefusal> = {
  verification_required: "verification",
  org_unavailable: "orgUnavailable",
  not_poster: "notPoster",
  events_daily_limit: "dailyLimit",
  invalid_event: "invalid",
  not_cancellable: "notCancellable",
  not_draft: "alreadyDecided",
  already_decided: "alreadyDecided",
  changed_since_review: "changedSinceReview",
  event_over: "eventOver",
  organisation_unavailable: "organisationUnavailable",
  step_up_required: "stepUp",
  mfa_enrolment_required: "mfaSetup",
  mfa_required: "mfaCode",
};

function fieldIssues(error: unknown): FieldIssue[] {
  const list = detailOf(error)?.errors;
  if (!Array.isArray(list)) return [];
  const out: FieldIssue[] = [];
  for (const item of list) {
    if (!isRecord(item) || typeof item.field !== "string" || typeof item.code !== "string") continue;
    const field = API_FIELDS[item.field];
    if (!field || out.some((issue) => issue.field === field)) continue;
    const code = (FIELD_CODES as readonly string[]).includes(item.code) ? (item.code as FieldCode) : "other";
    out.push({ field, code });
  }
  return out;
}

/** The refusal of an events call: a 422 with its fields, the rest by code or status. */
export function eventRefusalOf(status: number, error: unknown): EventRefused {
  const code = apiErrorCode(error);
  if (code && code in CODES) {
    const refusal = CODES[code];
    return { ok: false, refusal, fields: refusal === "invalid" ? fieldIssues(error) : [] };
  }
  const refusal: EventRefusal =
    status === 401
      ? "signedOut"
      : status === 404
        ? "notFound"
        : status === 403
          ? "forbidden"
          : status === 409
            ? "alreadyDecided"
            : status === 422 || status === 400
              ? "invalid"
              : "generic";
  return { ok: false, refusal, fields: [] };
}

export const EVENT_NETWORK: EventRefused = { ok: false, refusal: "network", fields: [] };

export type EventOutcome<T> = { ok: true; value: T } | EventRefused;

/** One call settled into its value or its refusal, never a thrown error. */
export async function settleEvent<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<EventOutcome<T>> {
  try {
    const { data, error, response } = await call;
    if (data !== undefined && response.ok) return { ok: true, value: data };
    return eventRefusalOf(response.status, error);
  } catch {
    return EVENT_NETWORK;
  }
}
