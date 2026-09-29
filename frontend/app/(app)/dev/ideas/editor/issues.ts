import { useCallback } from "react";

import { useStrings } from "@/components/ClientStrings";

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

function maxFor({ field, code }: FieldIssue): number | undefined {
  if (code === "too_many_words") return MAX_SUMMARY_WORDS;
  if (code === "tooMany") return MAX_LINKS;
  if (code === "tooLong") return LIMITS.link;
  if (code === "too_long" && field in LIMITS) return LIMITS[field as keyof typeof LIMITS];
  return undefined;
}

/** A function from an issue to its sentence. */
export function useIssueMessage() {
  const t = useStrings("ideaEditor");
  return useCallback(
    (issue: FieldIssue): string => {
      if (issue.code === "required") return t(`required.${requiredKey(issue.field)}`);
      // A code without its own message (a finding added to the API later) gets the general one.
      const key = `issue.${issue.code}` as "issue.other";
      const message = t(key, { max: maxFor(issue) ?? 0 });
      return message === `ideaEditor.${key}` ? t("issue.other") : message;
    },
    [t],
  );
}
