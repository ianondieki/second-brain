import { EMPTY_STATE, type EditorState, type MyProposal, type Version } from "./ideas";

// Loading a version into the editor happens on the server (EditorScreen); kept out of the editor's bundle.

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
