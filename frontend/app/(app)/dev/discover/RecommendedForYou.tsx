import Link from "next/link";
import { useTranslations } from "next-intl";

import { ConsiderIcon, NotNowIcon, PursueIcon } from "@/components/discover-icons";
import { problemHref } from "@/components/problem/problem";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { textLinkClass, titleLinkClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { cn } from "@/components/ui/cn";
import { LinkPending } from "@/components/ui/LinkPending";
import { Section } from "@/components/ui/Section";

import { cardBadges, ChipList, MoreSummary, WhyChip } from "./Chips";
import { DISCOVER_PATH, NICHES_PATH, PROFILING_HREF, startProposalHref } from "./discover";
import {
  DECISION_KEY,
  FIT_KEY,
  explain,
  type Decision,
  type Recommendation,
  type RecommendationsState,
} from "./recommendations";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

// Status as icon + words + tone (docs/platform/design/p16-design-system.md, Status): "Pursue" in the success tone, the
// others neutral; the accent stays for "act here".
const DECISION_TONE: Record<Decision, BadgeTone> = {
  pursue: "ok",
  consider: "neutral",
  not_now: "neutral",
};
const DECISION_ICON = { pursue: PursueIcon, consider: ConsiderIcon, not_now: NotNowIcon } as const;

/** The grid's columns by count: one, two or three across, never a third card alone under two. */
const GRID: Record<number, string> = { 1: "", 2: "md:grid-cols-2", 3: "md:grid-cols-3" };

/**
 * Home's "Recommended for you" (REQ-PERS-01; docs/spec/06 6.7): the first few recommendations, each with the pursuit
 * chip ("Pursue · Good fit") and one Why chip (docs/spec/07 item 2), the reasons, Why and Why not behind a disclosure,
 * and a one-line note on what the ranking uses with a link to the profiling setting (D-47). Without liked niches the
 * picker prompt shows instead; with nothing to recommend, an empty state (one sentence, one action).
 */
export function RecommendedForYou({ state }: { state: RecommendationsState }) {
  const t = useTranslations("recommendations");
  return (
    <Section
      title={t("title")}
      headingId="home-recommended"
      data-home="recommended"
      description={
        state.kind === "list" ? (
          <span data-personalised={state.personalised ? "on" : "off"}>
            {t.rich(state.personalised ? "personalisedOn" : "personalisedOff", {
              link: (chunks) => (
                <Link href={PROFILING_HREF} className={textLinkClass}>
                  {chunks}
                </Link>
              ),
            })}
          </span>
        ) : undefined
      }
    >
      {state.kind === "list" ? (
        <>
          {/* Three across on a wide column (no two-and-an-orphan), the cards as tall as their row. */}
          <ol className={cn("grid grid-cols-1 gap-4 [&>li]:min-w-0", GRID[Math.min(state.items.length, 3)])}>
            {state.items.map((item) => (
              <li key={item.problem.id}>
                <RecommendationRow item={item} />
              </li>
            ))}
          </ol>
          <p className="mt-3">
            <StandaloneLink href={DISCOVER_PATH}>{t("more")}</StandaloneLink>
          </p>
        </>
      ) : state.kind === "noNiches" ? (
        <EmptyState sentence={t("noNiches")} action={t("noNichesAction")} href={NICHES_PATH} />
      ) : (
        <EmptyState
          sentence={state.kind === "empty" ? t("empty") : t("unavailable")}
          action={t("emptyAction")}
          href={DISCOVER_PATH}
        />
      )}
    </Section>
  );
}

/**
 * One recommendation as a compact card (P20): the problem (its title the link to the problem's page), one meta line
 * (the niche, and the demo honesty label when it is a seeded example), the two chips in their own row, and the
 * explanation on demand at the foot. Only the title is a link: the disclosure is a control of its own.
 */
export function RecommendationRow({ item }: { item: Recommendation }) {
  const t = useTranslations("recommendations");
  const { decision } = item.pursuit;
  const pursuit = t(`pursuit.${DECISION_KEY[decision]}`);
  const DecisionIcon = DECISION_ICON[decision];
  const { lead: why, reasons, fits } = explain(item);
  const titleId = `recommended-${item.problem.id}`;
  const badges = cardBadges([
    <Badge key="pursuit" data-chip="pursuit" tone={DECISION_TONE[decision]} icon={<DecisionIcon />}>
      {t("chip", { pursuit, fit: t(`fit.${FIT_KEY[item.label]}`) })}
    </Badge>,
    why ? <WhyChip key="why">{why}</WhyChip> : null,
  ]);

  return (
    <article
      aria-labelledby={titleId}
      data-recommendation={item.problem.id}
      data-decision={decision}
      className="relative flex h-full min-w-0 flex-col rounded-panel border border-line bg-field p-4 transition-[border-color] duration-(--motion-fast) hover:border-accent-line sm:p-5"
    >
      <h3 id={titleId} className="text-base leading-snug font-semibold text-pretty [overflow-wrap:anywhere] text-ink">
        <Link href={problemHref(item.problem.id)} className={cn(titleLinkClass, "-my-[11px] inline-block py-[11px]")}>
          {item.problem.title}
          <LinkPending className="absolute -top-px left-4 sm:left-5" />
        </Link>
      </h3>
      {item.problem.niche || item.problem.label ? (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-soft">
          {item.problem.niche ? <span className="[overflow-wrap:anywhere]">{item.problem.niche.label}</span> : null}
          <ProblemLabelText problem={item.problem} />
        </p>
      ) : null}
      {badges ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {badges}
        </div>
      ) : null}
      <div className="mt-auto pt-2">
        {item.exploring ? <p className="text-sm text-ink-soft">{t("exploring")}</p> : null}
        <details className="group">
          <MoreSummary>{t("details")}</MoreSummary>
          <div className="mt-1 mb-2 flex max-w-[65ch] flex-col gap-4">
            {reasons.length > 0 ? (
              <section>
                <h4 className="text-sm font-semibold text-ink">{t("reasonsTitle", { pursuit })}</h4>
                <div className="mt-1">
                  <ChipList items={reasons} />
                </div>
              </section>
            ) : null}
            {fits.length > 0 ? (
              <section>
                <h4 className="text-sm font-semibold text-ink">{t("whyTitle")}</h4>
                <div className="mt-1">
                  <ChipList items={fits} />
                </div>
              </section>
            ) : null}
            {item.why_not ? (
              <section>
                <h4 className="text-sm font-semibold text-ink">{t("whyNotTitle")}</h4>
                <p className="mt-1 text-ink">{item.why_not}</p>
              </section>
            ) : null}
            <p>
              <StandaloneLink href={startProposalHref(item.problem.id)}>
                {t("start")}
              </StandaloneLink>
            </p>
          </div>
        </details>
      </div>
    </article>
  );
}
