import type { EditorState, MyProposal, ProblemRef, Version } from "./ideas";

// Loading a version into the editor happens on the server (EditorScreen); kept out of the editor's bundle.

/** A new idea's fields. */
export const EMPTY_STATE: EditorState = {
  title: "",
  nicheId: "",
  countyCode: "",
  maturity: "",
  ask: "",
  problemStatement: "",
  summary: "",
  impactClaims: "",
  problemMode: null,
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
    problemMode: version.problems.length > 0 ? "pick" : newProblem ? "new" : null,
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

/**
 * A new idea's fields with one published problem already linked (Discover's "Start a proposal from this problem"): the
 * problem is picked and its niche, when it has one, is the idea's. Nothing is saved until the developer types.
 */
export function stateWithProblem(problem: ProblemRef): EditorState {
  return { ...EMPTY_STATE, nicheId: problem.niche?.id ?? "", problemMode: "pick", problems: [problem] };
}
