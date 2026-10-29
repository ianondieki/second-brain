import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { topicLabel } from "@/app/(app)/dev/quiz/quiz";
import { Badge } from "@/components/ui/Badge";
import { DataCell, DataRow, dataLinkClass } from "@/components/ui/DataTable";
import { InfoIcon, PencilIcon } from "@/components/ui/icons";
import { formatMoment } from "@/lib/format";

import { seededTrend, trendReviewHref, type TrendCandidate } from "./trends";

/**
 * One trend card waiting for review, a row of the Trends table: its title (the way into the review) with its summary
 * and how it was drafted (one badge), then its topic and when it was drafted. Its sources are read on its page.
 */
export async function TrendRow({ card }: { card: TrendCandidate }) {
  const [t, tq, locale] = await Promise.all([getTranslations("adminResearch"), getTranslations("quiz"), getLocale()]);
  const seeded = seededTrend(card);
  return (
    <DataRow data-trend-candidate={card.id}>
      <DataCell head label={t("trends.columns.card")} className="sm:w-[50%]">
        <Link href={trendReviewHref(card.id)} className={dataLinkClass}>
          {card.title}
        </Link>
        <p className="mt-1 line-clamp-2 max-w-[52ch] text-sm [overflow-wrap:anywhere] text-ink-soft">{card.summary}</p>
        <p className="mt-2">
          <Badge tone="accent" icon={seeded ? <InfoIcon /> : <PencilIcon />}>
            {seeded ? t("trends.seeded") : t("trends.aiDrafted")}
          </Badge>
        </p>
      </DataCell>
      <DataCell label={t("trends.columns.topic")}>{topicLabel(tq, card.topic_slug)}</DataCell>
      <DataCell label={t("trends.columns.drafted")} figure nowrap className="text-ink-soft">
        {formatMoment(locale, card.created_at)}
      </DataCell>
    </DataRow>
  );
}
