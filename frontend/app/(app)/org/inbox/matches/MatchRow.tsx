import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Chip } from "@/components/tracker/Chip";

import { formatDay } from "../../format";
import type { Match } from "../../scout";
import { FitMeter, Why } from "./MatchParts";

/**
 * One scout match in the Inbox (REQ-SCOUT-02): its fit, when the scout found it, the title (a link to the match page),
 * the developer's pseudonymous handle (never a name or an id: docs/spec/06 6.1), the niche and why it matches. A
 * match whose proposal was unpublished or held shows only that it is no longer available: no teaser, no why.
 */
export function MatchRow({ match, href }: { match: Match; href: string }) {
  const t = useTranslations("scoutMatches");
  const locale = useLocale();
  const available = match.available && match.teaser !== null;
  const title = available ? (match.teaser?.title ?? t("unavailableTitle")) : t("unavailableTitle");
  return (
    <article
      className="flex min-w-0 flex-col gap-2 border-t border-line py-5"
      data-match={match.id}
      data-available={available ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        {available ? <FitMeter score={match.score} /> : <Chip kind="ended">{t("unavailable")}</Chip>}
        <p className="text-sm text-ink-soft">
          <time dateTime={match.created_at}>{t("found", { date: formatDay(locale, match.created_at) })}</time>
        </p>
      </div>
      <h2 className="text-lg leading-snug">
        <Link
          href={href}
          className={
            "-my-2 inline-flex min-h-11 items-center py-2 font-semibold [overflow-wrap:anywhere] text-ink " +
            "underline decoration-transparent decoration-1 underline-offset-[0.2em] hover:decoration-jacaranda"
          }
        >
          {title}
        </Link>
      </h2>
      {available ? (
        <>
          <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">
            {match.owner_handle ? <span className="block">{t("by", { handle: match.owner_handle })}</span> : null}
            <span className="block">{match.niche?.label ?? t("nicheNotGiven")}</span>
          </p>
          <div className="mt-1">
            <Why match={match} />
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-soft">{t("unavailableNote")}</p>
      )}
    </article>
  );
}
