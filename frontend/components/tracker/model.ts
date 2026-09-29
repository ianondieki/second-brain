import type { components, paths } from "@/lib/api/schema";

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

/** The 5-group stepper, in order (Review · Contact and NDA · Agreement · Implementation · Close). */
export const GROUPS = ["review", "contact_nda", "agreement", "implementation", "close"] as const;
export type Group = (typeof GROUPS)[number];

/** ✓ Completed · ● Current · ○ Pending · ⏸ On hold · ⚠ Overdue · ✕ Ended (docs/spec/06 6.9). */
export type ChipKind = "completed" | "current" | "pending" | "onHold" | "overdue" | "ended";

export const ENDED_STATES: ReadonlySet<State> = new Set(["DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED"]);
const PAUSED_STATES: ReadonlySet<State> = new Set(["ON_HOLD", "DISPUTED"]);

/** Terminal: nothing more happens (CLOSED is the successful end). */
export function isFinished(state: State): boolean {
  return state === "CLOSED" || ENDED_STATES.has(state);
}

/**
 * Where each main-path stage sits in the stepper, as backend state_machine.STAGE_GROUPS has it. The API sends
 * `stage_group` for the current stage, so this is read only for an engagement that ended or paused (the API sends
 * null then) to find the group it stopped in, from the stage it left (its last history event).
 */
const MAIN_PATH_GROUP: Partial<Record<State, Group>> = {
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

/** The stage an ended or paused engagement left: the `from_state` of the event that entered its current state. */
export function stageLeft(state: State, events: readonly HistoryEvent[] | null | undefined): State | null {
  if (!events) return null;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].to_state === state && events[i].from_state) return events[i].from_state;
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
  /** For an ended or paused engagement: the stage it left (stageLeft). */
  left?: State | null;
}): Step[] {
  const { state } = input;
  if (state === "CLOSED") return GROUPS.map((group) => ({ group, chip: "completed" }));
  const at =
    asGroup(input.stage_group) ?? (input.left ? MAIN_PATH_GROUP[input.left] : undefined) ?? GROUPS[0];
  const index = GROUPS.indexOf(at);
  const here: ChipKind = ENDED_STATES.has(state)
    ? "ended"
    : PAUSED_STATES.has(state)
      ? "onHold"
      : input.due?.overdue
        ? "overdue"
        : "current";
  return GROUPS.map((group, i) => ({ group, chip: i < index ? "completed" : i === index ? here : "pending" }));
}

/** The one chip a list row shows for where an engagement stands. */
export function stageChip(item: Pick<Summary, "state" | "due">): ChipKind {
  if (item.state === "CLOSED") return "completed";
  if (ENDED_STATES.has(item.state)) return "ended";
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

// --------------------------------------------------------------------------------------------- actions → requests

/** Commands whose request carries more than `lock_version`: each opens a small form first. */
export const FORM_COMMANDS = ["approve", "decline", "propose_terms", "record_payment", "confirm_payment"] as const;
export type FormCommand = (typeof FORM_COMMANDS)[number];

/** Commands that end the engagement: a confirmation first, never the primary button. */
export const ENDING_COMMANDS = ["withdraw", "decline_interest", "decline"] as const satisfies readonly Command[];

/** The milestone sub-tracker's commands, with the milestone states each can start from (state_machine.MILESTONE_STEPS). */
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
export type FormInput = ApproveInput | DeclineInput | TermsInput | PaymentInput | ConfirmPaymentInput;

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
  const at = new Date(iso);
  const date = new Intl.DateTimeFormat(`${locale}-KE`, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Nairobi",
  }).format(at);
  const time = new Intl.DateTimeFormat(`${locale}-KE`, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Africa/Nairobi",
  }).format(at);
  return { date, time };
}

/** A calendar date from the API ("2026-10-02") as written in Kenya ("2 Oct 2026"); dates carry no time zone. */
export function formatDate(day: string, locale = "en"): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(`${locale}-KE`, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

/** Today's date in Nairobi ("2026-09-29"), for date inputs. */
export function nairobiToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(now);
}

/** The first 12 hex digits of a SHA-256, grouped for reading ("3f5a 9c01 7be2"). */
export function shortHash(hex: string): string {
  return (hex.slice(0, 12).match(/.{1,4}/g) ?? []).join(" ");
}
