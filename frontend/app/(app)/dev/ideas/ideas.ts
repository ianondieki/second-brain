import type { components } from "@/lib/api/schema";

// Types, limits and pure helpers of Developer › My ideas (REQ-PROP-01; docs/spec/06 6.1, 6.3). The types come from
// the generated schema (backend/openapi.json); nothing here calls the API.

type Schemas = components["schemas"];
export type MyProposalItem = Schemas["MyProposalItem"];
export type MyProposal = Schemas["MyProposalOut"];
export type Version = Schemas["VersionOut"];
export type DraftBody = Schemas["DraftIn"];
export type Maturity = Schemas["ProposalMaturity"];
export type Ask = Schemas["ProposalAsk"];
export type ProblemRef = Schemas["ProblemRef"];
export type ProblemCard = Schemas["ProblemCard"];
export type Attachment = Schemas["AttachmentOut"];
export type AttestationText = Schemas["AttestationText"];
export type Attestations = Schemas["AttestationsIn"];
export type NicheNode = Schemas["NicheNode"];
export type County = Schemas["CountyRef"];
export type PublishResult = Schemas["PublishOut"];
export type Removed = Schemas["RemovedOut"];

export const BASE_PATH = "/dev/ideas";
export const NEW_PATH = "/dev/ideas/new";

/** The API's limits (bridge/proposals/schemas.py and sanitise.py). Inputs stop at them, so the API never refuses a
 * length the screen allowed. Browsers count UTF-16 units, the API code points, so the screen is never looser. */
export const LIMITS = {
  title: 120,
  summary: 1500,
  problem_statement: 2000,
  impact_claims: 1000,
  "new_problem.title": 90,
  "new_problem.statement": 2000,
  approach: 20000,
  architecture: 20000,
  pricing: 5000,
  notes: 5000,
  link: 500,
} as const;
export const MAX_SUMMARY_WORDS = 150;
export const MAX_LINKS = 10;
export const MAX_PROBLEMS = 5;
export const MAX_ATTACHMENTS = 10;
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

export const MATURITIES = ["idea", "prototype", "mvp", "live"] as const satisfies readonly Maturity[];
export const ASKS = ["sale", "licence", "co_build", "pilot", "hire"] as const satisfies readonly Ask[];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function isProposalId(value: string): boolean {
  return UUID.test(value);
}

export function ideaHref(id: string): string {
  return `${BASE_PATH}/${encodeURIComponent(id)}`;
}

export function editHref(id: string, step?: Step): string {
  return `${ideaHref(id)}/edit${step && step > 1 ? `?step=${step}` : ""}`;
}

// --- status ----------------------------------------------------------------------------------------------------------

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

// --- the editor's state ----------------------------------------------------------------------------------------------

export type Step = 1 | 2 | 3;
export const STEPS = [1, 2, 3] as const satisfies readonly Step[];

export function parseStep(value: string | string[] | undefined): Step {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "2" ? 2 : raw === "3" ? 3 : 1;
}

export type ProblemMode = "pick" | "new";

/** Everything the three steps edit, as the inputs hold it (strings; "" is empty). */
export interface EditorState {
  title: string;
  nicheId: string;
  countyCode: string;
  maturity: Maturity | "";
  ask: Ask | "";
  problemStatement: string;
  summary: string;
  impactClaims: string;
  problemMode: ProblemMode;
  problems: ProblemRef[];
  newProblemTitle: string;
  newProblemStatement: string;
  approach: string;
  architecture: string;
  pricing: string;
  notes: string;
  /** One link per line. */
  links: string;
}

export const EMPTY_STATE: EditorState = {
  title: "",
  nicheId: "",
  countyCode: "",
  maturity: "",
  ask: "",
  problemStatement: "",
  summary: "",
  impactClaims: "",
  problemMode: "pick",
  problems: [],
  newProblemTitle: "",
  newProblemStatement: "",
  approach: "",
  architecture: "",
  pricing: "",
  notes: "",
  links: "",
};

/** The version the editor continues: the draft when there is one, else the published one (the first save copies it
 * into the next version). */
export function editableVersion(proposal: MyProposal): Version | null {
  return proposal.draft ?? proposal.current;
}

export function stateFromVersion(version: Version | null): EditorState {
  if (!version) return EMPTY_STATE;
  const { teaser, confidential, new_problem: newProblem } = version;
  return {
    title: teaser.title ?? "",
    nicheId: teaser.niche?.id ?? "",
    countyCode: teaser.county_code ?? "",
    maturity: teaser.maturity ?? "",
    ask: teaser.ask ?? "",
    problemStatement: teaser.problem_statement ?? "",
    summary: teaser.summary ?? "",
    impactClaims: teaser.impact_claims ?? "",
    problemMode: newProblem && version.problems.length === 0 ? "new" : "pick",
    problems: version.problems,
    newProblemTitle: newProblem?.title ?? "",
    newProblemStatement: newProblem?.statement ?? "",
    approach: confidential.approach ?? "",
    architecture: confidential.architecture ?? "",
    pricing: confidential.pricing ?? "",
    notes: confidential.notes ?? "",
    links: confidential.links.join("\n"),
  };
}

const orNull = (value: string) => (value.trim() === "" ? null : value);

/** The non-empty lines of the links box. */
export function linkLines(links: string): string[] {
  return links
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export type LinkProblem = "tooMany" | "notWeb" | "tooLong";

/** Why the links cannot be saved as typed, or null. The API accepts http and https addresses only. */
export function linksProblem(links: string): LinkProblem | null {
  const lines = linkLines(links);
  if (lines.length > MAX_LINKS) return "tooMany";
  for (const line of lines) {
    if (line.length > LIMITS.link) return "tooLong";
    let url: URL;
    try {
      url = new URL(line);
    } catch {
      return "notWeb";
    }
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname) return "notWeb";
  }
  return null;
}

export interface DraftPlan {
  body: DraftBody;
  /** Parts left out of this save because the API would refuse them as typed; the field shows why. */
  held: Array<"links" | "newProblem">;
}

/**
 * The PATCH (or POST) body for the whole state: every field is sent (the API applies what is sent, and null clears).
 * The problem not chosen is cleared: picking listed problems clears a described one and the other way round. Links
 * that are not web addresses, and a half-written new problem, are left out rather than refused.
 */
export function draftBody(state: EditorState): DraftPlan {
  const held: DraftPlan["held"] = [];
  const body: DraftBody = {
    teaser: {
      title: orNull(state.title),
      niche_id: orNull(state.nicheId),
      county_code: orNull(state.countyCode),
      maturity: state.maturity || null,
      ask: state.ask || null,
      problem_statement: orNull(state.problemStatement),
      summary: orNull(state.summary),
      impact_claims: orNull(state.impactClaims),
    },
    confidential: {
      approach: orNull(state.approach),
      architecture: orNull(state.architecture),
      pricing: orNull(state.pricing),
      notes: orNull(state.notes),
    },
  };
  if (linksProblem(state.links)) held.push("links");
  else body.confidential!.links = linkLines(state.links);

  if (state.problemMode === "pick") {
    body.problem_ids = state.problems.map((problem) => problem.id);
    body.new_problem = null;
  } else {
    body.problem_ids = [];
    const title = state.newProblemTitle.trim();
    const statement = state.newProblemStatement.trim();
    if (title && statement) body.new_problem = { title, statement, niche_id: orNull(state.nicheId) };
    else if (!title && !statement) body.new_problem = null;
    else held.push("newProblem");
  }
  return { body, held };
}

// --- checks before publishing ----------------------------------------------------------------------------------------

/** Field names as the API reports them (422 `invalid_teaser` and `cannot_publish`), plus the screen's own. */
export type FieldName =
  | "title"
  | "niche_id"
  | "county_code"
  | "maturity"
  | "ask"
  | "problem_statement"
  | "summary"
  | "impact_claims"
  | "problems"
  | "new_problem.title"
  | "new_problem.statement"
  | "links";

export const FIELD_STEP: Record<FieldName, Step> = {
  title: 1,
  niche_id: 1,
  county_code: 1,
  maturity: 1,
  ask: 1,
  problem_statement: 1,
  summary: 1,
  impact_claims: 1,
  problems: 1,
  "new_problem.title": 1,
  "new_problem.statement": 1,
  links: 2,
};

const FIELD_NAMES = new Set<string>(Object.keys(FIELD_STEP));
export function isFieldName(value: string): value is FieldName {
  return FIELD_NAMES.has(value);
}

/** Words as a reader counts them (runs of non-space characters). */
export function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/u).length : 0;
}

export interface FieldIssue {
  field: FieldName;
  code: string;
}

/**
 * What still stops publishing, as far as the screen can tell (the API checks again and has the last word): the
 * required teaser fields, a problem, the summary's word limit and a finished new problem.
 */
export function publishChecklist(state: EditorState): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const required: Array<[FieldName, string]> = [
    ["title", state.title],
    ["niche_id", state.nicheId],
    ["maturity", state.maturity],
    ["ask", state.ask],
    ["problem_statement", state.problemStatement],
    ["summary", state.summary],
  ];
  for (const [field, value] of required) if (!value.trim()) issues.push({ field, code: "required" });
  if (wordCount(state.summary) > MAX_SUMMARY_WORDS) issues.push({ field: "summary", code: "too_many_words" });
  if (state.problemMode === "pick" && state.problems.length === 0) {
    issues.push({ field: "problems", code: "problem_required" });
  }
  if (state.problemMode === "new") {
    if (!state.newProblemTitle.trim()) issues.push({ field: "new_problem.title", code: "required" });
    if (!state.newProblemStatement.trim()) issues.push({ field: "new_problem.statement", code: "required" });
  }
  if (linksProblem(state.links)) issues.push({ field: "links", code: linksProblem(state.links)! });
  return issues;
}

// --- niches and attachments ------------------------------------------------------------------------------------------

/** A niche's label ("ICT › Networks & Telecoms") by id, for showing a chosen niche. */
export function nicheLabel(niches: readonly NicheNode[], id: string): string | undefined {
  for (const parent of niches) {
    if (parent.id === id) return parent.label;
    const child = parent.children.find((c) => c.id === id);
    if (child) return child.label;
  }
  return undefined;
}

// The attachment types the API accepts (bridge/proposals/editor.py ACCEPTED_TYPES), by file extension: browsers
// give Markdown files no type or several different ones, so the extension decides what is sent.
const TYPE_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  md: "text/markdown",
  markdown: "text/markdown",
  txt: "text/plain",
};

export const ACCEPT_ATTRIBUTE = ".pdf,.png,.jpg,.jpeg,.md,.markdown,.txt";

export function attachmentType(name: string): string | null {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? null : (TYPE_BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? null);
}

/** File sizes as people read them: "820 KB", "4.2 MB" (1 KB = 1,000 bytes, as the size limit is stated). */
export function fileSizeParts(bytes: number): { value: number; unit: "bytes" | "kb" | "mb" } {
  if (bytes < 1000) return { value: bytes, unit: "bytes" };
  if (bytes < 1_000_000) return { value: Math.round(bytes / 1000), unit: "kb" };
  return { value: Math.round(bytes / 100_000) / 10, unit: "mb" };
}
