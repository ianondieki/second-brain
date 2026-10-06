import { getTranslations } from "next-intl/server";

import { Row } from "@/components/ui/RowList";

import { trendHref, type TrendCard } from "./week";

/**
 * The trend of the day as one row (Home's strip, /dev/week): its title as the link to the card, "Trend" as the plain
 * fact under it, then one line of its summary ("Read more" is the card itself).
 */
export async function TrendRow({ trend }: { trend: TrendCard }) {
  const t = await getTranslations("week");
  return (
    <Row
      data-week-trend={trend.id}
      href={trendHref(trend.id)}
      title={trend.title}
      meta={<span className="font-medium text-accent">{t("strip.trend")}</span>}
    >
      <p className="line-clamp-1 text-sm text-ink-soft">{trend.summary}</p>
    </Row>
  );
}
