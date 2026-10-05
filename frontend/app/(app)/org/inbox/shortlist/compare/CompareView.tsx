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
const FACTS: readonly Fact[] = ["niche", "place", "maturity", "ask", "registered", "engagement", "fit"];

export interface CompareViewProps {
  items: readonly CompareItem[];
  memberships: Membership[];
  org: Membership;
  counties: readonly County[];
}

/**
 * The compared proposals (Tier 1 only): from 1024 px a calm table, one column per proposal under its title (a link to
 * the proposal page) and the facts' names in a first column that stays in place when the table scrolls sideways; below
 * 1024 px one card per proposal with its facts as rows. Only one of the two is displayed at a width (the other is
 * `display: none`, so out of the accessibility tree too).
 */
export function CompareView({ items, memberships, org, counties }: CompareViewProps) {
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
        const county = item.county_code ? counties.find((c) => c.code === item.county_code)?.name : undefined;
        if (county) return county;
        return item.country ? countryName(item.country, locale) : none(ti("notStated"));
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

  const cell = "py-3.5 pr-5 align-top text-left last:pr-0";
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
              <td className="sticky left-0 bg-field" />
              {items.map((item) => (
                <th key={item.proposal_id} scope="col" className={cn(cell, "pt-5 align-bottom text-base font-semibold text-ink")}>
                  <Link href={href(item)} className={cn(titleLinkClass, "[overflow-wrap:anywhere]")}>
                    {title(item)}
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FACTS.map((fact) => (
              <tr key={fact} data-fact={fact} className="border-b border-line last:border-b-0">
                <th scope="row" className={cn(cell, "sticky left-0 bg-field pl-5 font-normal text-ink-soft")}>
                  {t(`fact.${fact}`)}
                </th>
                {items.map((item) => (
                  <td key={item.proposal_id} className={cn(cell, "text-ink [overflow-wrap:anywhere]")}>
                    {value(item, fact)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Below 1024 px: one card per proposal. */}
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:hidden" data-compare="cards">
        {items.map((item) => (
          <li key={item.proposal_id} className="min-w-0 rounded-panel border border-line bg-field p-5">
            <h2 className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
              <Link href={href(item)} className={titleLinkClass}>
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

/** "KE" as the reader's language names it ("Kenya"), or the code when the runtime cannot. */
function countryName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}
