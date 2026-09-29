import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { LIMITS, MAX_LINKS, MAX_SUMMARY_WORDS, type FieldIssue, type FieldName } from "../ideas";

// The words for one field issue, from the editor's own [[COPY-REVIEW]] strings (never the API's message).

/** Message keys under ideaEditor.required.* (the API's field names hold dots and underscores). */
const REQUIRED_KEY = {
  title: "title",
  niche_id: "niche",
  maturity: "maturity",
  ask: "ask",
  problem_statement: "problemStatement",
  summary: "summary",
  "new_problem.title": "newProblemTitle",
  "new_problem.statement": "newProblemStatement",
} as const satisfies Partial<Record<FieldName, string>>;

type RequiredKey = (typeof REQUIRED_KEY)[keyof typeof REQUIRED_KEY] | "other";

function requiredKey(field: FieldName): RequiredKey {
  return field in REQUIRED_KEY ? REQUIRED_KEY[field as keyof typeof REQUIRED_KEY] : "other";
}

const ISSUE_CODES = [
  "contains_url",
  "contains_domain",
  "contains_email",
  "contains_phone",
  "contains_payment_number",
  "too_long",
  "too_many_words",
  "problem_required",
  "unknown",
  "notWeb",
  "tooMany",
  "tooLong",
] as const;
type IssueCode = (typeof ISSUE_CODES)[number];
const KNOWN_CODES: ReadonlySet<string> = new Set(ISSUE_CODES);
const isIssueCode = (code: string): code is IssueCode => KNOWN_CODES.has(code);

function maxFor({ field, code }: FieldIssue): number | undefined {
  if (code === "too_many_words") return MAX_SUMMARY_WORDS;
  if (code === "tooMany") return MAX_LINKS;
  if (code === "tooLong") return LIMITS.link;
  if (code === "too_long" && field in LIMITS) return LIMITS[field as keyof typeof LIMITS];
  return undefined;
}

/** A function from an issue to its sentence. */
export function useIssueMessage() {
  const t = useTranslations("ideaEditor");
  return useCallback(
    (issue: FieldIssue): string => {
      if (issue.code === "required") return t(`required.${requiredKey(issue.field)}`);
      if (isIssueCode(issue.code)) return t(`issue.${issue.code}`, { max: maxFor(issue) ?? 0 });
      return t("issue.other");
    },
    [t],
  );
}

/** The field's label key under ideaFields.* for the review step's list. */
export const FIELD_LABEL = {
  title: "title",
  niche_id: "niche",
  county_code: "county",
  maturity: "maturity",
  ask: "ask",
  problem_statement: "problemStatement",
  summary: "summary",
  impact_claims: "impactClaims",
  problems: "problems",
  "new_problem.title": "newProblemTitle",
  "new_problem.statement": "newProblemStatement",
  links: "links",
} as const satisfies Record<FieldName, string>;
