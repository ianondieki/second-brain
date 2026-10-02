import { getLocale, getTranslations } from "next-intl/server";

import { startProposalHref } from "@/app/(app)/dev/discover/discover";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { todayInNairobi } from "@/app/(app)/org/brief-draft";
import { formatCalendarDate } from "@/lib/format";

import type { ProblemDetail } from "./problem";

/**
 * The problem page's one action for a developer (REQ-TREND-02, REQ-DIR-05): "Start a proposal from this brief" while
 * an organisation's Brief is open (published, not closed, deadline not passed: the API's `brief.open`), so its pitch
 * later starts with the organisation chosen; for any other problem, and a Brief no longer asking for proposals, the
 * plain "Start a proposal from this problem", with a quiet line saying which: closed, or past its deadline (on which day).
 */
export async function ProblemStart({ problem }: { problem: ProblemDetail }) {
  const t = await getTranslations("discover");
  const tp = await getTranslations("problem");
  const locale = await getLocale();
  const brief = problem.source === "org_brief" ? (problem.brief ?? null) : null;
  const open = brief?.open === true;
  // Not open: past its deadline when the deadline is before today in Nairobi, else the organisation closed it (or
  // staff took it down; the developer reads the same sentence).
  const past = brief && !open && brief.deadline !== null && brief.deadline < todayInNairobi() ? brief.deadline : null;
  return (
    <div className="flex flex-col items-start gap-2">
      <ButtonLink href={startProposalHref(problem.id)} variant="primary" data-start={open ? "brief" : "problem"}>
        {open ? t("startBrief") : t("start")}
      </ButtonLink>
      {brief && !open ? (
        <p className="max-w-[62ch] text-sm text-ink-soft" data-brief-ended="">
          {past ? tp("briefEnded.pastDeadline", { date: formatCalendarDate(locale, past) }) : tp("briefEnded.closed")}
        </p>
      ) : null}
    </div>
  );
}
