import { getTranslations } from "next-intl/server";

import { Row } from "@/components/ui/RowList";

import { trendHref, type TrendCard } from "./week";

/**
 * The trend of the day as one row (Home's strip, /dev/week): its title as the link to the card, "Trend" as the plain
 * fact under it, then one line of its summary on Home (two on /dev/week; "Read more" is the card itself).
 */
export async function TrendRow({ trend, lines = 1 }: { trend: TrendCard; lines?: 1 | 2 }) {
  const t = await getTranslations("week");
  return (
    <Row
      data-week-trend={trend.id}
      href={trendHref(trend.id)}
      title={trend.title}
      meta={<span className="font-medium text-accent">{t("strip.trend")}</span>}
    >
      <p className={lines === 1 ? "line-clamp-1 text-sm text-ink-soft" : "line-clamp-2 text-sm text-ink-soft"}>{trend.summary}</p>
    </Row>
  );
}
