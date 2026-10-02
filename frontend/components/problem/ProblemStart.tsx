import { getTranslations } from "next-intl/server";

import { startProposalHref } from "@/app/(app)/dev/discover/discover";
import { ButtonLink } from "@/components/ui/ButtonLink";

import type { ProblemDetail } from "./problem";

/**
 * The problem page's one action for a developer (REQ-TREND-02, REQ-DIR-05): "Start a proposal from this brief" while
 * an organisation's Brief is open (published, not closed, deadline not passed: the API's `brief.open`), so its pitch
 * later starts with the organisation chosen; for any other problem, and a Brief no longer asking for proposals, the
 * plain "Start a proposal from this problem", with a quiet line saying the Brief is closed or past its deadline.
 */
export async function ProblemStart({ problem }: { problem: ProblemDetail }) {
  const t = await getTranslations("discover");
  const tp = await getTranslations("problem");
  const brief = problem.source === "org_brief" ? (problem.brief ?? null) : null;
  const open = brief?.open === true;
  return (
    <div className="flex flex-col items-start gap-2">
      <ButtonLink href={startProposalHref(problem.id)} variant="primary" data-start={open ? "brief" : "problem"}>
        {open ? t("startBrief") : t("start")}
      </ButtonLink>
      {brief && !open ? (
        <p className="max-w-[62ch] text-sm text-ink-soft" data-brief-ended="">
          {tp("briefEnded")}
        </p>
      ) : null}
    </div>
  );
}
