import Link from "next/link";
import { useTranslations } from "next-intl";

import { ConsiderIcon, NotNowIcon, PursueIcon } from "@/components/discover-icons";
import { problemHref } from "@/components/problem/problem";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { textLinkClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Row, RowList } from "@/components/ui/RowList";
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
          <RowList ordered cards>
            {state.items.map((item) => (
              <RecommendationRow key={item.problem.id} item={item} />
            ))}
          </RowList>
          <StandaloneLink href={DISCOVER_PATH}>
            {t("more")}
          </StandaloneLink>
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

/** One recommendation, a Row: the problem (a link to its card), two badges, and the explanation on demand. */
export function RecommendationRow({ item }: { item: Recommendation }) {
  const t = useTranslations("recommendations");
  const { decision } = item.pursuit;
  const pursuit = t(`pursuit.${DECISION_KEY[decision]}`);
  const DecisionIcon = DECISION_ICON[decision];
  const { lead: why, reasons, fits } = explain(item);
  const titleId = `recommended-${item.problem.id}`;

  return (
    <Row
      aria-labelledby={titleId}
      data-recommendation={item.problem.id}
      data-decision={decision}
      title={item.problem.title}
      titleId={titleId}
      href={problemHref(item.problem.id)}
      stretch={false}
      meta={
        item.problem.niche || item.problem.label ? (
          <span className="flex flex-wrap gap-x-4">
            {item.problem.niche ? <span>{item.problem.niche.label}</span> : null}
            <ProblemLabelText problem={item.problem} />
          </span>
        ) : undefined
      }
      badges={cardBadges([
        <Badge key="pursuit" data-chip="pursuit" tone={DECISION_TONE[decision]} icon={<DecisionIcon />}>
          {t("chip", { pursuit, fit: t(`fit.${FIT_KEY[item.label]}`) })}
        </Badge>,
        why ? <WhyChip key="why">{why}</WhyChip> : null,
      ])}
    >
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
    </Row>
  );
}
