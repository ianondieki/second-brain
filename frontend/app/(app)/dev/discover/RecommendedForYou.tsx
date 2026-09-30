import Link from "next/link";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/app/(app)/org/EmptyState";
import { ConsiderIcon, NotNowIcon, PursueIcon } from "@/components/discover-icons";
import { standaloneLinkClass, textLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import { ChipList, Chips, MoreSummary } from "./Chips";
import { DISCOVER_PATH, NICHES_PATH, problemHref, PROFILING_HREF, startProposalHref } from "./discover";
import { titleLinkClass } from "./ProblemRow";
import {
  DECISION_KEY,
  FIT_KEY,
  leadWhy,
  type Decision,
  type Recommendation,
  type RecommendationsState,
} from "./recommendations";

const DECISION_TONE: Record<Decision, string> = {
  pursue: "text-ok",
  consider: "text-jacaranda",
  not_now: "text-ink-soft",
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
    <section aria-labelledby="home-recommended" data-home="recommended">
      <h2 id="home-recommended" className="text-lg text-ink">
        {t("title")}
      </h2>
      {state.kind === "list" ? (
        <>
          <p data-personalised={state.personalised ? "on" : "off"} className="mt-1 max-w-[62ch] text-sm text-ink-soft">
            {t.rich(state.personalised ? "personalisedOn" : "personalisedOff", {
              link: (chunks) => (
                <Link href={PROFILING_HREF} className={textLinkClass}>
                  {chunks}
                </Link>
              ),
            })}
          </p>
          <ol className="mt-2 border-b border-line">
            {state.items.map((item) => (
              <li key={item.problem.id}>
                <RecommendationRow item={item} />
              </li>
            ))}
          </ol>
          <Link href={DISCOVER_PATH} className={cn(standaloneLinkClass, "mt-2")}>
            {t("more")}
          </Link>
        </>
      ) : (
        <div className="mt-2">
          {state.kind === "noNiches" ? (
            <EmptyState sentence={t("noNiches")} action={t("noNichesAction")} href={NICHES_PATH} />
          ) : (
            <EmptyState
              sentence={state.kind === "empty" ? t("empty") : t("unavailable")}
              action={t("emptyAction")}
              href={DISCOVER_PATH}
            />
          )}
        </div>
      )}
    </section>
  );
}

/** One recommendation: the problem (a link to its card), two chips, and the explanation on demand. */
export function RecommendationRow({ item }: { item: Recommendation }) {
  const t = useTranslations("recommendations");
  const { decision } = item.pursuit;
  const pursuit = t(`pursuit.${DECISION_KEY[decision]}`);
  const DecisionIcon = DECISION_ICON[decision];
  const why = leadWhy(item);
  const titleId = `recommended-${item.problem.id}`;

  return (
    <article
      aria-labelledby={titleId}
      data-recommendation={item.problem.id}
      data-decision={decision}
      className="flex min-w-0 flex-col gap-2 border-t border-line py-4"
    >
      <h3 id={titleId} className="text-base leading-snug">
        <Link href={problemHref(item.problem.id)} className={titleLinkClass}>
          {item.problem.title}
        </Link>
      </h3>
      <Chips items={why ? [why] : []}>
        <li data-chip="pursuit" className={cn("inline-flex items-start gap-1.5 text-sm font-semibold", DECISION_TONE[decision])}>
          <DecisionIcon className="mt-0.5 size-4 shrink-0" />
          <span>{t("chip", { pursuit, fit: t(`fit.${FIT_KEY[item.label]}`) })}</span>
        </li>
      </Chips>
      {item.exploring ? <p className="text-sm text-ink-soft">{t("exploring")}</p> : null}
      <details className="group">
        <MoreSummary>{t("details")}</MoreSummary>
        <div className="mt-2 flex max-w-[65ch] flex-col gap-4 border-l-2 border-jacaranda-wash pl-4">
          <section>
            <h4 className="text-sm font-semibold text-ink">{t("reasonsTitle", { pursuit })}</h4>
            <div className="mt-1">
              <ChipList items={item.pursuit.reasons} />
            </div>
          </section>
          <section>
            <h4 className="text-sm font-semibold text-ink">{t("whyTitle")}</h4>
            <div className="mt-1">
              <ChipList items={item.why} />
            </div>
          </section>
          {item.why_not ? (
            <section>
              <h4 className="text-sm font-semibold text-ink">{t("whyNotTitle")}</h4>
              <p className="mt-1 text-ink">{item.why_not}</p>
            </section>
          ) : null}
          <p>
            <Link href={startProposalHref(item.problem.id)} className={standaloneLinkClass}>
              {t("start")}
            </Link>
          </p>
        </div>
      </details>
    </article>
  );
}
