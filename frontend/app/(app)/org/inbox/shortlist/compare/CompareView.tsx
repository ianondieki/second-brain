import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import { formatDay } from "../../../format";
import { MATURITY_KEY } from "../../../labels";
import { engagementsHref, proposalHref, type Membership } from "../../../membership";
import type { County } from "../../../scout-data";
import type { CompareItem } from "../../../shortlist";
import { StageChip } from "../../../StageChip";
import { FitMeter } from "../../matches/MatchParts";

type Fact = "niche" | "place" | "maturity" | "ask" | "registered" | "engagement" | "fit";
/** A title link's tap area: 44 px tall (WCAG 2.5.8) without moving the text (the padding is taken back). */
const TARGET = "-my-2.5 inline-block py-2.5";

const FACTS: readonly Fact[] = ["niche", "place", "maturity", "ask", "registered", "engagement", "fit"];

export interface CompareViewProps {
  items: readonly CompareItem[];
  memberships: Membership[];
  org: Membership;
  counties: readonly County[];
  /** Each proposal's niche photograph band by its id (NicheBand, from the server page), over its column or card. */
  bands?: Readonly<Record<string, ReactNode>>;
}

/**
 * The compared proposals (Tier 1 only): from 1024 px a calm table, one column per proposal under its niche's
 * photograph band and its title (a link to
 * the proposal page) and the facts' names in a first column that stays in place when the table scrolls sideways; below
 * 1024 px one card per proposal with its facts as rows. Only one of the two is displayed at a width (the other is
 * `display: none`, so out of the accessibility tree too).
 */
export function CompareView({ items, memberships, org, counties, bands = {} }: CompareViewProps) {
  const t = useTranslations("shortlist");
  const ti = useTranslations("inbox");
  const tf = useTranslations("ideaFields");
  const locale = useLocale();

  const title = (item: CompareItem) => item.title ?? ti("untitled");
  const href = (item: CompareItem) => proposalHref(memberships, org.org_id, item.proposal_id);
  const none = (text: string) => <span className="text-ink-soft">{text}</span>;

  function value(item: CompareItem, fact: Fact): ReactNode {
    switch (fact) {
      case "niche":
        return item.niche ? item.niche.label : none(ti("notStated"));
      case "place": {
        // The row is "County", as on the teaser: a proposal without a county says so (never its country instead).
        const county = item.county_code ? counties.find((c) => c.code === item.county_code)?.name : undefined;
        return county ?? none(ti("notStated"));
      }
      case "maturity":
        return item.maturity ? tf(MATURITY_KEY[item.maturity]) : none(ti("notStated"));
      case "ask":
        return item.ask ? ti(`ask.${item.ask}`) : none(ti("notStated"));
      case "registered":
        return item.registered_at ? (
          <span className="flex flex-col items-start">
            <time dateTime={item.registered_at} className="tabular-nums">
              {formatDay(locale, item.registered_at)}
            </time>
            {item.cert_id ? (
              <StandaloneLink
                href={`/verify/${encodeURIComponent(item.cert_id)}`}
                className="-my-1.5 text-sm [overflow-wrap:anywhere]"
                aria-label={t("certificateNamed", { title: title(item) })}
              >
                {t("certificate")}
              </StandaloneLink>
            ) : null}
          </span>
        ) : (
          none(ti("notStated"))
        );
      case "engagement":
        return item.engagement ? (
          <StageChip
            engagement={item.engagement}
            href={engagementsHref(memberships, org.org_id, item.engagement.id)}
          />
        ) : (
          none(t("noEngagement"))
        );
      case "fit":
        return item.fit_score === null ? none(t("notMatched")) : <FitMeter score={item.fit_score} />;
    }
  }

  const cell = "py-3.5 pr-5 align-top text-left";
  return (
    <>
      {/* From 1024 px: the table. */}
      <div className="hidden overflow-x-auto rounded-panel border border-line bg-field lg:block" data-compare="table">
        <table className="w-full min-w-[40rem] table-fixed border-collapse text-sm">
          <caption className="sr-only">{t("tableCaption", { count: items.length })}</caption>
          <colgroup>
            <col className="w-40" />
            {items.map((item) => (
              <col key={item.proposal_id} />
            ))}
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              <td className="compare-sticky sticky left-0 bg-field" />
              {items.map((item) => (
                <th key={item.proposal_id} scope="col" className={cn(cell, "pt-4 align-bottom text-base font-semibold text-ink")}>
                  {bands[item.proposal_id] ? <div className="compare-band mb-3">{bands[item.proposal_id]}</div> : null}
                  <Link href={href(item)} className={cn(titleLinkClass, TARGET, "[overflow-wrap:anywhere]")}>
                    {title(item)}
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FACTS.map((fact) => (
              <tr key={fact} data-fact={fact} className="border-b border-line last:border-b-0">
                <th scope="row" className={cn(cell, "compare-sticky sticky left-0 bg-field pl-5 font-normal text-ink-soft")}>
                  {t(`fact.${fact}`)}
                </th>
                {items.map((item) => (
                  <td key={item.proposal_id} className={cn(cell, "text-ink tabular-nums [overflow-wrap:anywhere]")}>
                    {value(item, fact)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Below 1024 px: one card per proposal, two across only for an even count (never two-and-one). */}
      <ul
        className={cn("grid grid-cols-1 gap-4 lg:hidden", items.length % 2 === 0 && "sm:grid-cols-2")}
        data-compare="cards"
      >
        {items.map((item) => (
          <li key={item.proposal_id} className="min-w-0 overflow-hidden rounded-panel border border-line bg-field p-5">
            {bands[item.proposal_id] ? <div className="compare-band -mx-5 -mt-5 mb-4">{bands[item.proposal_id]}</div> : null}
            <h2 className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
              <Link href={href(item)} className={cn(titleLinkClass, TARGET)}>
                {title(item)}
              </Link>
            </h2>
            <dl className="mt-3 flex flex-col">
              {FACTS.map((fact) => (
                <div
                  key={fact}
                  data-fact={fact}
                  className="grid grid-cols-[8rem_minmax(0,1fr)] gap-3 border-t border-line py-2.5 text-sm first:border-t-0"
                >
                  <dt className="text-ink-soft">{t(`fact.${fact}`)}</dt>
                  <dd className="text-ink [overflow-wrap:anywhere]">{value(item, fact)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
