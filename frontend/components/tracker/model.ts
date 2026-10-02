import type { components, paths } from "@/lib/api/schema";
import { formatCalendarDate, nairobiParts } from "@/lib/format";

// The tracker's view model (REQ-ENG-03; docs/spec/06 6.9 Rendering): what the screens draw from the API's engagement.
// Nothing here decides who may act: the buttons come only from the API's `actions` for the caller, whose turn it is
// from `whose_turn` and `awaiting`, the stepper's current group from `stage_group` (backend state_machine.py).

type Schemas = components["schemas"];
export type Detail = Schemas["EngagementDetail"];
export type Summary = Schemas["EngagementSummary"];
export type Command = Schemas["Command"];
export type Party = Schemas["EngagementParty"];
export type State = Schemas["EngagementState"];
export type Endorsement = Schemas["EndorsementOut"];
export type Agreement = Schemas["AgreementOut"];
export type Milestone = Schemas["MilestoneOut"];
export type MilestoneState = Schemas["MilestoneState"];
export type Signature = Schemas["SignatureOut"];
export type Payment = Schemas["PaymentOut"];
export type HistoryEvent = Schemas["HistoryEventOut"];
export type History = Schemas["HistoryOut"];
export type DocumentKind = Schemas["SignatureDocumentKind"];
export type Due = Schemas["DueOut"];
export type Note = Schemas["NoteOut"];

/** The 5-group stepper, in order (Review · Contact and NDA · Agreement · Implementation · Close). */
export const GROUPS = ["review", "contact_nda", "agreement", "implementation", "close"] as const;
export type Group = (typeof GROUPS)[number];

/** ✓ Completed · ● Current · ○ Pending · ⏸ On hold · ⚠ Overdue · ✕ Ended (docs/spec/06 6.9). */
export type ChipKind = "completed" | "current" | "pending" | "onHold" | "overdue" | "ended";

export const ENDED_STATES: ReadonlySet<State> = new Set(["DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED"]);
/**
 * Side states an engagement leaves only for the stage it entered them from (state_machine.RETURNING, pinned by
 * state-machine-parity.test.ts): the stepper keeps that stage marked, with the On hold chip (docs/spec/06 6.9 "banner
 * on the stage where they occurred, never extra steps").
 */
export const PAUSED_STATES: ReadonlySet<State> = new Set(["ON_HOLD", "DISPUTED", "INFO_REQUESTED"]);

/** Terminal: nothing more happens (CLOSED is the successful end). */
export function isFinished(state: State): boolean {
  return state === "CLOSED" || ENDED_STATES.has(state);
}

/**
 * Where each main-path stage sits in the stepper, as backend state_machine.STAGE_GROUPS has it (the state machine is
 * the only definition: state-machine-parity.test.ts fails when the two differ). The API sends `stage_group` for the
 * current stage, so this is read only for an engagement that ended or paused (the API sends null then) to find the
 * group it stopped in, from the stage it left (its last history event).
 */
export const MAIN_PATH_GROUP: Partial<Record<State, Group>> = {
  ORG_INTEREST: "review",
  SUBMITTED: "review",
  UNDER_REVIEW: "review",
  INTEREST_CONFIRMED: "contact_nda",
  CONTACT_MADE: "contact_nda",
  NDA_PENDING: "contact_nda",
  NDA_SIGNED: "contact_nda",
  NEGOTIATION: "agreement",
  AGREEMENT_SIGNING: "agreement",
  IN_IMPLEMENTATION: "implementation",
  DELIVERED: "implementation",
  SIGN_OFF: "close",
  PAYMENT_FINAL: "close",
  CLOSED: "close",
};

export function asGroup(value: string | null | undefined): Group | null {
  return (GROUPS as readonly string[]).includes(value ?? "") ? (value as Group) : null;
}

/**
 * The stage an ended or paused engagement left: the `from_state` of the event that entered its current state, and
 * through a side state to the stage before it (a question left unanswered expires from INFO_REQUESTED).
 */
export function stageLeft(state: State, events: readonly HistoryEvent[] | null | undefined): State | null {
  if (!events) return null;
  for (let i = events.length - 1; i >= 0; i--) {
    const from = events[i].from_state;
    if (events[i].to_state !== state || !from) continue;
    return PAUSED_STATES.has(from) ? (stageLeft(from, events.slice(0, i)) ?? from) : from;
  }
  return null;
}

export interface Step {
  group: Group;
  chip: ChipKind;
}

/**
 * The five groups with their chips. Groups before the current one are completed, later ones pending; the current one
 * is current, overdue (past its deadline), on hold, or ended (declined, withdrawn, expired, terminated). A closed
 * engagement has every group completed.
 */
export function stepperSteps(input: {
  state: State;
  stage_group: string | null;
  due: Due | null;
  /** A paused engagement: the stage it returns to (the API's `paused_from`), which stays marked. */
  paused_from?: State | null;
  /** For an ended engagement (or a paused one the API sent no `paused_from` for): the stage it left (stageLeft). */
  left?: State | null;
}): Step[] {
  if (input.state === "CLOSED") return GROUPS.map((group) => ({ group, chip: "completed" }));
  const stage = input.paused_from ?? input.left;
  const at = asGroup(input.stage_group) ?? (stage ? MAIN_PATH_GROUP[stage] : undefined) ?? GROUPS[0];
  const index = GROUPS.indexOf(at);
  const here = stageChip(input);
  return GROUPS.map((group, i) => ({ group, chip: i < index ? "completed" : i === index ? here : "pending" }));
}

/**
 * The chip for where an engagement stands (a list row's, and the stepper's current group): ✕ once ended (an expiry
 * too), ⏸ while paused, except ⚠ for a question left past its answer-by date (the engagement expires at the clock's
 * next pass), ⚠ past the stage's deadline, else ●. A hold's date is when it resumes, never overdue.
 */
export function stageChip(item: Pick<Summary, "state" | "due">): ChipKind {
  if (item.state === "CLOSED") return "completed";
  if (ENDED_STATES.has(item.state)) return "ended";
  if (item.state === "INFO_REQUESTED" && item.due?.overdue) return "overdue";
  if (PAUSED_STATES.has(item.state)) return "onHold";
  return item.due?.overdue ? "overdue" : "current";
}

export type Turn =
  | { kind: "ended" }
  | { kind: "none" }
  | { kind: "you" }
  | { kind: "other"; party: Party }
  | { kind: "both" };

/** Whose turn it is, for the caller (`whose_turn` from the API; `mine` is the caller's party). */
export function turnOf(item: Pick<Summary, "state" | "whose_turn">, mine: Party): Turn {
  if (isFinished(item.state)) return { kind: "ended" };
  const parties = new Set(item.whose_turn);
  if (parties.size === 0) return { kind: "none" };
  if (parties.size > 1) return { kind: "both" };
  return parties.has(mine) ? { kind: "you" } : { kind: "other", party: [...parties][0] };
}

/** True when the engagement waits on the caller's party. */
export function awaitsMe(item: Pick<Summary, "state" | "whose_turn">, mine: Party): boolean {
  return !isFinished(item.state) && item.whose_turn.includes(mine);
}

/** The next steps the caller's party owes (`awaiting`), without repeats. */
export function myNextSteps(detail: Pick<Detail, "awaiting" | "my_party">): Command[] {
  return [...new Set(detail.awaiting.filter((p) => p.party === detail.my_party).map((p) => p.command))];
}

/** The steps the other party owes. */
export function theirNextSteps(detail: Pick<Detail, "awaiting" | "my_party">): Command[] {
  return [...new Set(detail.awaiting.filter((p) => p.party !== detail.my_party).map((p) => p.command))];
}

/**
 * The main path from the organisation's approval on (state_machine.CONTACT_REVEALED, pinned by
 * state-machine-parity.test.ts): the stages in which the named contact may reveal the developer's contact details.
 */
export const CONTACT_REVEALED_STATES: ReadonlySet<State> = new Set([
  "INTEREST_CONFIRMED",
  "CONTACT_MADE",
  "NDA_PENDING",
  "NDA_SIGNED",
  "NEGOTIATION",
  "AGREEMENT_SIGNING",
  "IN_IMPLEMENTATION",
  "DELIVERED",
  "SIGN_OFF",
  "PAYMENT_FINAL",
  "CLOSED",
]);

/**
 * Whether to offer "Show the developer's contact details": only to the organisation's named contact person, and only
 * in the stages where the API reveals them (never before the approval, never on a declined, withdrawn or expired
 * engagement). The API decides again on the request.
 */
export function offersContactReveal(
  detail: Pick<Detail, "my_party" | "contact" | "state">,
  userId: string,
): boolean {
  return detail.my_party === "org" && detail.contact?.user_id === userId && CONTACT_REVEALED_STATES.has(detail.state);
}

/** Stages whose rows show both parties' endorsements (docs/spec/06 6.9: 0, 4, 5, 8, 11, 12 and TERMINATED). */
export const DUAL_ENDORSEMENT_STATES: ReadonlySet<State> = new Set([
  "ORG_INTEREST",
  "CONTACT_MADE",
  "NDA_PENDING",
  "AGREEMENT_SIGNING",
  "SIGN_OFF",
  "PAYMENT_FINAL",
  "TERMINATED",
]);

/** The current stage's endorsement by each party (this round; milestone endorsements are shown with the milestone). */
export function endorsementRows(detail: Pick<Detail, "endorsements" | "state">): Record<Party, Endorsement | null> {
  const stage = detail.endorsements.filter((e) => e.milestone_id === null && e.stage === detail.state);
  return {
    developer: stage.find((e) => e.party === "developer") ?? null,
    org: stage.find((e) => e.party === "org") ?? null,
  };
}

/** Document kinds in stage order. */
export const DOCUMENT_KINDS: readonly DocumentKind[] = [
  "mutual_nda",
  "agreement",
  "acceptance_certificate",
  "milestone_confirmation",
];

/**
 * The documents the engagement has so far, in stage order. The API's `documents` lists the current stage's document
 * only, so the signed ones (their signatures) and a final or signed agreement are added; GET …/documents/{kind} serves
 * each. Milestone confirmations have no document route yet.
 */
export function documentKinds(detail: Pick<Detail, "documents" | "signatures" | "agreements">): DocumentKind[] {
  const found = new Set<DocumentKind>(detail.documents.map((d) => d.kind));
  for (const s of detail.signatures) found.add(s.document_kind);
  if (detail.agreements.some((a) => a.status !== "draft")) found.add("agreement");
  return DOCUMENT_KINDS.filter((kind) => kind !== "milestone_confirmation" && found.has(kind));
}

// --------------------------------------------------------------------------------------------- side states

/**
 * What the whose-turn banner says about a side state (docs/spec/06 6.9: a banner on the stage where it occurred,
 * never an extra step), from the API's state and `notes` (in event order):
 * - `info`: the organisation's open question (its latest `info_request` note);
 * - `hold`: the reason and resume date of the latest `hold` note;
 * - `expired`: the system ended it (the end reason says why);
 * - `answered`: the stage resumed with the developer's answer (the latest note is the `info_answer` written when
 *   the engagement entered its current stage).
 */
export type SideBanner =
  | { kind: "info"; question: Note | null }
  | { kind: "hold"; hold: Note | null }
  | { kind: "expired"; reason: Detail["end_reason"] }
  | { kind: "answered"; answer: Note };

/** Note and event times come from the same transaction; allow for rounding between the two. */
const SAME_EVENT_MS = 2_000;

function latest(notes: readonly Note[], kind: Note["kind"]): Note | null {
  for (let i = notes.length - 1; i >= 0; i--) if (notes[i].kind === kind) return notes[i];
  return null;
}

export function sideBanner(detail: Pick<Detail, "state" | "notes" | "end_reason" | "stage_entered_at">): SideBanner | null {
  const notes = detail.notes ?? [];
  if (detail.state === "INFO_REQUESTED") return { kind: "info", question: latest(notes, "info_request") };
  if (detail.state === "ON_HOLD") return { kind: "hold", hold: latest(notes, "hold") };
  if (detail.state === "EXPIRED") return { kind: "expired", reason: detail.end_reason };
  const last = notes.at(-1);
  if (
    last?.kind === "info_answer" &&
    !isFinished(detail.state) &&
    Date.parse(last.at) >= Date.parse(detail.stage_entered_at) - SAME_EVENT_MS
  ) {
    return { kind: "answered", answer: last };
  }
  return null;
}

/** The note kind each side-state command writes (a hold resumed by the system at its date writes none). */
const NOTE_OF: Partial<Record<string, Note["kind"]>> = {
  request_info: "info_request",
  answer_info: "info_answer",
  pause: "hold",
  resume: "resume",
};

/**
 * Each history event's note, by event id: the n-th event of a command that writes a note of a kind gets the n-th note
 * of that kind (one note per event, both in event order; the system's resume writes none and is left out).
 */
export function notesByEvent(events: readonly HistoryEvent[], notes: readonly Note[]): Map<string, Note> {
  const queues = new Map<Note["kind"], Note[]>();
  for (const note of notes) queues.set(note.kind, [...(queues.get(note.kind) ?? []), note]);
  const found = new Map<string, Note>();
  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    const kind = NOTE_OF[event.command];
    if (!kind || event.actor_role === "system") continue;
    const note = queues.get(kind)?.shift();
    if (note) found.set(event.id, note);
  }
  return found;
}

/** A calendar date `days` after another ("2026-10-02" + 60), for the hold's latest resume date. */
export function addDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** A calendar date with its weekday, as a person says it ("Monday, 12 October 2026"; Swahili "Jumatatu, 12 Oktoba 2026"). */
export function longDate(day: string, locale = "en"): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

// --------------------------------------------------------------------------------------------- actions → requests

/** Commands whose request carries more than `lock_version`: each opens a small form first. */
export const FORM_COMMANDS = ["approve", "decline", "propose_terms", "record_payment", "confirm_payment"] as const;
export type FormCommand = (typeof FORM_COMMANDS)[number];

/**
 * The side states' commands (REQ-ENG-10 part): each opens a sheet over the tracker (a bottom sheet on phones), four
 * with a text the other party reads (a question, an answer, a reason) and the organisation's withdrawal of its
 * question as a confirmation.
 */
export const SHEET_COMMANDS = ["request_info", "answer_info", "pause", "resume", "cancel_request"] as const satisfies readonly Command[];
export type SheetCommand = (typeof SHEET_COMMANDS)[number];

/** The longest question or answer, and the longest reason (state_machine.QUESTION_MAX_CHARS / REASON_MAX_CHARS). */
export const QUESTION_MAX_CHARS = 2000;
export const REASON_MAX_CHARS = 500;
/** A hold's resume date: at most this many calendar days ahead (policy.yaml on_hold.max_days). */
export const HOLD_MAX_DAYS = 60;

/** Commands that end the engagement: a confirmation first, never the primary button. */
export const ENDING_COMMANDS = ["withdraw", "decline_interest", "decline"] as const satisfies readonly Command[];

/**
 * The milestone sub-tracker's commands, with the milestone states each can start from (state_machine.MILESTONE_STEPS;
 * pinned to it by state-machine-parity.test.ts). Used only to put each button on the milestones that can take it.
 */
export const MILESTONE_STEPS = {
  start_milestone: ["PLANNED", "CHANGES_REQUESTED"],
  submit_milestone: ["IN_PROGRESS"],
  accept_milestone: ["SUBMITTED_FOR_REVIEW"],
  request_changes: ["SUBMITTED_FOR_REVIEW"],
} as const satisfies Partial<Record<Command, readonly MilestoneState[]>>;
export type MilestoneCommand = keyof typeof MILESTONE_STEPS;

export function isFormCommand(command: Command): command is FormCommand {
  return (FORM_COMMANDS as readonly string[]).includes(command);
}

export function isSheetCommand(command: Command): command is SheetCommand {
  return (SHEET_COMMANDS as readonly string[]).includes(command);
}

export function isMilestoneCommand(command: Command): command is MilestoneCommand {
  return command in MILESTONE_STEPS;
}

export function isEndingCommand(command: Command): boolean {
  return (ENDING_COMMANDS as readonly string[]).includes(command);
}

/** The signed agreement (its milestones are the sub-tracker's), else null. */
export function signedAgreement(agreements: readonly Agreement[]): Agreement | null {
  return agreements.find((a) => a.status === "signed") ?? null;
}

/** The milestones a sub-tracker command can take now (the API lists the command when at least one can). */
export function milestoneTargets(command: MilestoneCommand, agreements: readonly Agreement[]): Milestone[] {
  const from: readonly MilestoneState[] = MILESTONE_STEPS[command];
  return (signedAgreement(agreements)?.milestones ?? []).filter((m) => from.includes(m.state));
}

/** One button: a command, on one milestone for the sub-tracker's commands. */
export interface ActionItem {
  command: Command;
  milestone?: Milestone;
  primary: boolean;
}

/**
 * The caller's buttons, one per command in `actions` (one per milestone for the sub-tracker's). The primary one is
 * the first step the engagement awaits from the caller's party (never a step that ends it); ending steps come last.
 */
export function actionItems(detail: Pick<Detail, "actions" | "awaiting" | "my_party" | "agreements">): ActionItem[] {
  const next = myNextSteps(detail).find((c) => detail.actions.includes(c) && !isEndingCommand(c));
  const items: ActionItem[] = [];
  for (const command of detail.actions) {
    if (isMilestoneCommand(command)) {
      for (const milestone of milestoneTargets(command, detail.agreements)) items.push({ command, milestone, primary: false });
    } else {
      items.push({ command, primary: false });
    }
  }
  const primary = items.find((item) => item.command === next);
  if (primary) primary.primary = true;
  const rank = (item: ActionItem) => (item.primary ? 0 : isEndingCommand(item.command) ? 2 : 1);
  return items.map((item, i) => ({ item, i })).sort((a, b) => rank(a.item) - rank(b.item) || a.i - b.i).map((x) => x.item);
}

const PREFIX = "/api/engagements/{engagement_id}" as const;

/** URL segment of each command without a milestone (backend engagements/router.py). */
export const COMMAND_SEGMENT = {
  accept_interest: "accept-interest",
  decline_interest: "decline-interest",
  start_review: "start-review",
  decline: "decline",
  approve: "approve",
  withdraw: "withdraw",
  mark_contacted: "mark-contacted",
  confirm_contact: "confirm-contact",
  send_nda: "send-nda",
  sign_nda: "sign-nda",
  propose_terms: "propose-terms",
  mark_final: "mark-final",
  reopen_negotiation: "reopen-negotiation",
  sign_agreement: "sign-agreement",
  deliver: "deliver",
  accept_delivery: "accept-delivery",
  sign_certificate: "sign-certificate",
  record_payment: "record-payment",
  confirm_payment: "confirm-payment",
  request_info: "request-info",
  answer_info: "answer-info",
  cancel_request: "cancel-request",
  pause: "pause",
  resume: "resume",
} as const satisfies Record<Exclude<Command, MilestoneCommand>, string>;

export const MILESTONE_SEGMENT = {
  start_milestone: "start",
  submit_milestone: "submit",
  accept_milestone: "accept",
  request_changes: "request-changes",
} as const satisfies Record<MilestoneCommand, string>;

/** Every path the tracker builds is a route of the frozen OpenAPI (a renamed route fails the type check here). */
type CommandPath =
  | `${typeof PREFIX}/${(typeof COMMAND_SEGMENT)[keyof typeof COMMAND_SEGMENT]}`
  | `${typeof PREFIX}/milestones/{milestone_id}/${(typeof MILESTONE_SEGMENT)[MilestoneCommand]}`;
export const COMMAND_PATHS_EXIST: [CommandPath] extends [keyof paths] ? true : never = true;

export type ApproveInput = Omit<Schemas["ApproveBody"], "lock_version">;
export type DeclineInput = Omit<Schemas["DeclineBody"], "lock_version">;
export type TermsInput = Omit<Schemas["TermsBody"], "lock_version">;
export type PaymentInput = Omit<Schemas["PaymentBody"], "lock_version">;
export type ConfirmPaymentInput = Omit<Schemas["ConfirmPaymentBody"], "lock_version">;
export type RequestInfoInput = Omit<Schemas["RequestInfoBody"], "lock_version">;
export type AnswerInfoInput = Omit<Schemas["AnswerInfoBody"], "lock_version">;
export type PauseInput = Omit<Schemas["PauseBody"], "lock_version">;
export type ResumeInput = Omit<Schemas["ResumeBody"], "lock_version">;
/** What a sheet sends: its text (and a hold's date); the withdrawal of a question sends nothing more. */
export type SheetInput = RequestInfoInput | AnswerInfoInput | PauseInput | ResumeInput | Record<string, never>;
export type FormInput =
  | ApproveInput
  | DeclineInput
  | TermsInput
  | PaymentInput
  | ConfirmPaymentInput
  | RequestInfoInput
  | AnswerInfoInput
  | PauseInput
  | ResumeInput;

/** One command request: the path template, its parameters and the JSON body (always with `lock_version`). */
export interface CommandRequest {
  path: string;
  params: { engagement_id: string; milestone_id?: string };
  body: { lock_version: number } & Partial<FormInput>;
}

/** The request for a command on an engagement read at `lockVersion` (a 409 `stale` when it changed since). */
export function commandRequest(
  command: Command,
  engagementId: string,
  lockVersion: number,
  { milestoneId, input }: { milestoneId?: string; input?: FormInput } = {},
): CommandRequest {
  const body = { ...(input ?? {}), lock_version: lockVersion };
  if (isMilestoneCommand(command)) {
    if (!milestoneId) throw new TypeError(`${command} needs a milestone`);
    return {
      path: `${PREFIX}/milestones/{milestone_id}/${MILESTONE_SEGMENT[command]}`,
      params: { engagement_id: engagementId, milestone_id: milestoneId },
      body,
    };
  }
  return { path: `${PREFIX}/${COMMAND_SEGMENT[command]}`, params: { engagement_id: engagementId }, body };
}

/** `path` with the page's query ("?org=…", kept for members of several organisations) and any other values. */
export function withQuery(path: string, query = "", extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(query);
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

// --------------------------------------------------------------------------------------------- formatting

/** KES from minor units, as people read it: "250,000" or "1,250.50" (the currency code comes from the message). */
export function kesAmount(minor: number, locale = "en"): string {
  const whole = minor % 100 === 0;
  return new Intl.NumberFormat(`${locale}-KE`, {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

/** Whole or decimal shillings typed in a form, as minor units; null when it is not a positive amount. */
export function toMinor(text: string): number | null {
  const clean = text.replace(/[,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  const minor = Math.round(Number(clean) * 100);
  return minor > 0 ? minor : null;
}

/** A moment in Nairobi time, as its date and time parts ("23 Sep 2026", "14:05"); the message adds "EAT". */
export function eatParts(iso: string, locale = "en"): { date: string; time: string } {
  return nairobiParts(locale, iso);
}

/** A calendar date from the API ("2026-10-02") as written in Kenya ("2 Oct 2026"); dates carry no time zone. */
export function formatDate(day: string, locale = "en"): string {
  return formatCalendarDate(locale, day);
}

/** Today's date in Nairobi ("2026-09-29"), for date inputs. */
export function nairobiToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(now);
}

/** The first 12 hex digits of a SHA-256, grouped for reading ("3f5a 9c01 7be2"). */
export function shortHash(hex: string): string {
  return (hex.slice(0, 12).match(/.{1,4}/g) ?? []).join(" ");
}

/**
 * The line under the tracker's title: the organisation, for the developer; for the organisation, the developer's
 * name, or while `developer_named` is false (before INTEREST_CONFIRMED) their handle, said to be a handle
 * (docs/spec/06 6.1). The API sends the handle in `developer_name` then; `developer_id` is never read.
 */
export function counterpartLine(
  detail: Pick<Detail, "my_party" | "org_name" | "developer_name" | "developer_named">,
): { key: "withOrg" | "fromDeveloper" | "fromHandle"; values: { org?: string; name?: string } } {
  if (detail.my_party === "developer") return { key: "withOrg", values: { org: detail.org_name } };
  return { key: detail.developer_named ? "fromDeveloper" : "fromHandle", values: { name: detail.developer_name } };
}
