import { linkLines, linksProblem, type DraftBody, type EditorState } from "./ideas";

// The save body, built only when saving: it loads with the editor's calls, not with the page.

const orNull = (value: string) => (value.trim() === "" ? null : value);

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

  if (state.problemMode === null) {
    // Not chosen yet: the problems saved so far stay as they are.
  } else if (state.problemMode === "pick") {
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
