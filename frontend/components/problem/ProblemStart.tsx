import { getLocale, getTranslations } from "next-intl/server";

import { startProposalHref } from "@/app/(app)/dev/discover/discover";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { formatCalendarDate } from "@/lib/format";

import type { ProblemDetail } from "./problem";

/**
 * The problem page's one action for a developer (REQ-TREND-02, REQ-DIR-05): "Start a proposal from this Brief" while
 * an organisation's Brief is open (the API's `brief.open`), so its pitch later starts with the organisation chosen; for
 * any other problem, and a Brief no longer asking for proposals, the plain "Start a proposal from this problem", with a
 * quiet line saying why from the API's `brief.ended`, decided on the platform clock: closed (it wins over a passed
 * deadline), or past its deadline (on which day). An API that does not say (`ended` absent or null) gets no guess:
 * the Brief is no longer open.
 */
export async function ProblemStart({ problem }: { problem: ProblemDetail }) {
  const t = await getTranslations("discover");
  const tp = await getTranslations("problem");
  const locale = await getLocale();
  const brief = problem.source === "org_brief" ? (problem.brief ?? null) : null;
  const open = brief?.open === true;
  const ended = brief?.ended ?? null;
  const why =
    ended === "closed"
      ? tp("briefEnded.closed")
      : ended === "past_deadline" && brief?.deadline
        ? tp("briefEnded.pastDeadline", { date: formatCalendarDate(locale, brief.deadline) })
        : tp("briefEnded.notOpen");
  return (
    <div className="flex flex-col items-start gap-2">
      <ButtonLink href={startProposalHref(problem.id)} variant="primary" data-start={open ? "brief" : "problem"}>
        {open ? t("startBrief") : t("start")}
      </ButtonLink>
      {brief && !open ? (
        <p className="max-w-[62ch] text-sm text-ink-soft" data-brief-ended={ended ?? "unknown"}>
          {why}
        </p>
      ) : null}
    </div>
  );
}
