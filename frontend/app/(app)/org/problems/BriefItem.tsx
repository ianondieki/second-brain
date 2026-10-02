import { useLocale, useTranslations } from "next-intl";

import { Chip } from "@/components/tracker/Chip";
import { Row } from "@/components/ui/RowList";
import { formatCalendarDate } from "@/lib/format";

import { STATE_CHIP, type Brief } from "../briefs";

/**
 * One of the organisation's Briefs in its list (REQ-DIR-05), a compact card (RowList cards): the title linking to the
 * Brief's page, one meta line (niche, county), one status mark (In review, Published, Not approved, Closed; docs/spec/07
 * item 2: at most two), then the proposals answering it and the deadline on one line.
 */
export function BriefItem({ brief, href, county }: { brief: Brief; href: string; county: string | null }) {
  const t = useTranslations("briefs");
  const locale = useLocale();
  const titleId = `brief-${brief.id}-title`;
  return (
    <Row
      aria-labelledby={titleId}
      data-brief={brief.id}
      data-state={brief.state}
      title={brief.title}
      titleId={titleId}
      // The page has no h2 above its list (docs/spec/07 item 6, axe heading-order): each Brief's title is one.
      headingLevel={2}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4">
          {brief.niche ? <span>{brief.niche.label}</span> : null}
          <span>{county ?? t("anywhere")}</span>
        </span>
      }
      badges={[
        <Chip key="state" kind={STATE_CHIP[brief.state]}>
          {t(`state.${brief.state}`)}
        </Chip>,
      ]}
    >
      <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
        <span data-proposals={brief.proposal_count}>{t("proposals", { count: brief.proposal_count })}</span>
        <span>{brief.deadline ? t("deadline", { date: formatCalendarDate(locale, brief.deadline) }) : t("noDeadline")}</span>
      </p>
    </Row>
  );
}
