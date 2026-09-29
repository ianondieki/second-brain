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
/** Message keys under ideaFields.maturityValue.* (next-intl refuses "prototype" as a key segment). */
export const MATURITY_KEY = {
  idea: "idea",
  prototype: "prototypeStage",
  mvp: "mvp",
  live: "live",
} as const satisfies Record<Maturity, string>;
export const ASKS = ["sale", "licence", "co_build", "pilot", "hire"] as const satisfies readonly Ask[];

export function ideaHref(id: string): string {
  return `${BASE_PATH}/${encodeURIComponent(id)}`;
}

export function editHref(id: string, step?: Step): string {
  return `${ideaHref(id)}/edit${step && step > 1 ? `?step=${step}` : ""}`;
}

// --- the editor's state ----------------------------------------------------------------------------------------------

export type Step = 1 | 2 | 3;
export const STEPS = [1, 2, 3] as const satisfies readonly Step[];

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
  /** Null until the developer chooses (a new idea asks first). */
  problemMode: ProblemMode | null;
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
  if (state.problemMode === null || (state.problemMode === "pick" && state.problems.length === 0)) {
    issues.push({ field: "problems", code: "problem_required" });
  }
  if (state.problemMode === "new") {
    if (!state.newProblemTitle.trim()) issues.push({ field: "new_problem.title", code: "required" });
    if (!state.newProblemStatement.trim()) issues.push({ field: "new_problem.statement", code: "required" });
  }
  if (linksProblem(state.links)) issues.push({ field: "links", code: linksProblem(state.links)! });
  return issues;
}
