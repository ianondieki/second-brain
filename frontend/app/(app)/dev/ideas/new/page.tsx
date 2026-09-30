import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EditorScreen } from "../editor/EditorScreen";
import { isProposalId } from "../routes";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("ideaEditor");
  return { title: t("pageTitleNew") };
}

/**
 * A new idea (REQ-PROP-01): nothing is created until the first save, a moment after you start typing. `?problem=<id>`
 * (Discover's "Start a proposal from this problem", REQ-TREND-02) starts it with that problem linked.
 */
export default async function NewIdeaPage({ searchParams }: PageProps<"/dev/ideas/new">) {
  const problem = (await searchParams).problem;
  const problemId = typeof problem === "string" && isProposalId(problem) ? problem : null;
  return <EditorScreen id={null} step={1} problemId={problemId} />;
}
