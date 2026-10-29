import type { components } from "@/lib/api/schema";

// Types, limits and pure helpers of "Pitch to companies" and the idea page's pitches (REQ-PROP-03, REQ-DIR-04; docs/spec/06
// 6.2 and 6.3). The types come from the generated schema (backend/openapi.json); nothing here calls the API, so the
// picker's client component and the server pages share it.

type Schemas = components["schemas"];
export type PitchPicker = Schemas["PitchPicker"];
export type PitchGroup = Schemas["PitchGroup"];
export type PitchOption = Schemas["PitchOption"];
export type PitchReason = NonNullable<PitchOption["reason"]>;
export type TagOut = Schemas["TagOut"];
export type TagCap = Schemas["TagCap"];
export type TagStatus = Schemas["TagStatus"];
export type MyTags = Schemas["MyTags"];
export type PitchResult = Schemas["PitchResult"];
export type ProposalViews = Schemas["ProposalViews"];
export type ViewOut = Schemas["ViewOut"];

/** The API's batch limit (TagsIn.org_ids: 1 to 20 organisations per Pitch). */
export const MAX_BATCH = 20;
/** Organisations per picker page: enough to scan, small enough for a phone on mobile data. */
export const PAGE_SIZE = 30;

export const PITCH_REASONS = [
  "own_organisation",
  "tagged",
  "open_elsewhere",
  "already_pitched",
  "cooldown",
  "unavailable",
] as const satisfies readonly PitchReason[];
type MissingReasons = Exclude<PitchReason, (typeof PITCH_REASONS)[number]>;
const everyReasonListed: [MissingReasons] extends [never] ? true : MissingReasons = true;
void everyReasonListed;

const REASONS: ReadonlySet<string> = new Set(PITCH_REASONS);
export function isPitchReason(value: unknown): value is PitchReason {
  return typeof value === "string" && REASONS.has(value);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * An organisation's id as the picker keys it (lower case): the URL, the API's cards, a refusal's ids and the chosen
 * set all compare through this one helper, so an id in another case can never slip past a check.
 */
export function orgKey(id: string): string {
  return id.toLowerCase();
}

export function isOrgId(value: string): boolean {
  return UUID.test(value);
}

export function pitchHref(proposalId: string, query: PickerQuery = { selected: [] }): string {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.niche) params.set("niche", query.niche);
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.org) params.set("org", query.org);
  for (const id of query.selected) params.append("sel", id);
  const text = params.toString();
  return `/dev/ideas/${encodeURIComponent(proposalId)}/pitch${text ? `?${text}` : ""}`;
}

// --- the picker's URL --------------------------------------------------------------------------------------------------

/** The picker's search, niche, page and the organisations already chosen (kept across searches as `sel`). */
export interface PickerQuery {
  q?: string;
  niche?: string;
  cursor?: string;
  selected: string[];
  /**
   * The organisation whose Problem Brief the idea answers (`?org=`, REQ-DIR-05): chosen from the start, first, and
   * the page says why. Its id only; the picker shows and sends it like any other choice, or not at all.
   */
  org?: string;
}

const NICHE_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function all(value: string | string[] | undefined): string[] {
  return value === undefined ? [] : Array.isArray(value) ? value : [value];
}

/** The picker's query, validated against the API's limits; anything malformed is left out, never sent. */
export function parsePickerQuery(params: SearchParams): PickerQuery {
  const out: PickerQuery = { selected: [] };
  const q = first(params.q)
    ?.replace(/\u0000/g, "")
    .trim();
  // At most 100 characters, cut by code point (a UTF-16 slice could leave a lone surrogate encodeURIComponent refuses).
  if (q) out.q = Array.from(q).slice(0, 100).join("");
  const niche = first(params.niche);
  if (niche && niche.length <= 80 && NICHE_SLUG.test(niche)) out.niche = niche;
  const cursor = first(params.cursor);
  if (cursor && cursor.length <= 2000) out.cursor = cursor;
  const seen = new Set<string>();
  const org = first(params.org);
  if (org && isOrgId(org)) {
    out.org = orgKey(org);
    seen.add(out.org);
    out.selected.push(out.org);
  }
  for (const id of all(params.sel)) {
    const lower = orgKey(id);
    if (!isOrgId(id) || seen.has(lower)) continue;
    seen.add(lower);
    out.selected.push(lower);
    if (out.selected.length === MAX_BATCH) break;
  }
  return out;
}

/** The query for GET /api/me/proposals/{id}/pitch/orgs. */
export function pickerApiQuery({ q, niche, cursor }: PickerQuery) {
  return { q, niche: niche ? [niche] : undefined, cursor, limit: PAGE_SIZE };
}

// --- the plan cap ------------------------------------------------------------------------------------------------------

/** Pitches left for this proposal on the plan, or null when the plan has no limit. */
export function pitchesLeft(cap: TagCap): number | null {
  return cap.limit === null ? null : Math.max(0, cap.limit - cap.used);
}

/** How many organisations one Pitch may name now: the batch limit, or fewer when the plan has fewer left. */
export function selectionMax(cap: TagCap): number {
  const left = pitchesLeft(cap);
  return left === null ? MAX_BATCH : Math.min(MAX_BATCH, left);
}

/** True when the plan's pitches left, not the batch limit, is what stops more choices. */
export function capBinds(cap: TagCap): boolean {
  const left = pitchesLeft(cap);
  return left !== null && left <= MAX_BATCH;
}

// --- tags --------------------------------------------------------------------------------------------------------------

/** A tag as the developer reads it: sent to the organisation, saved until it verifies, withdrawn, or closed. */
export type TagState = "sent" | "saved" | "withdrawn" | "closed";

export function isHeld(status: TagStatus): status is "held_unclaimed" | "held_pending_verification" {
  return status === "held_unclaimed" || status === "held_pending_verification";
}

export function tagState(tag: Pick<TagOut, "status" | "open">): TagState {
  if (tag.status === "withdrawn") return "withdrawn";
  if (!tag.open) return "closed";
  if (tag.status === "delivered") return "sent";
  if (isHeld(tag.status)) return "saved";
  return "closed";
}

/** Only an open held tag is withdrawn here; a delivered one is withdrawn on the tracker (409 `tag_delivered`). */
export function canWithdraw(tag: Pick<TagOut, "status" | "open">): boolean {
  return tag.open && isHeld(tag.status);
}

/** The held sentence of a status (docs/spec/06 6.2): E0 is not on the platform, E1 is still verifying. */
export function heldKey(status: TagStatus): "heldUnclaimed" | "heldPending" | null {
  if (status === "held_unclaimed") return "heldUnclaimed";
  if (status === "held_pending_verification") return "heldPending";
  return null;
}
