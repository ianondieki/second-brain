// The checks that run on what was typed (links, the publish checklist, the API's field names), apart from ideas.ts so
// the editor's first load does not carry them: the details step, the review step and the save path load them, and the
// editor reads the checklist only once a publish was attempted (docs/spec/07 item 5, the 150 KB budget).
import {
  LIMITS,
  MAX_LINKS,
  MAX_SUMMARY_WORDS,
  wordCount,
  type EditorState,
  type FieldIssue,
  type FieldName,
  type Step,
} from "./ideas";

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
