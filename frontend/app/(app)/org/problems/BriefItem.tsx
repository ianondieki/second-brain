import { useLocale, useTranslations } from "next-intl";

import { Chip } from "@/components/tracker/Chip";
import type { ReactNode } from "react";

import { ItemCard } from "../ItemCard";
import { formatCalendarDate } from "@/lib/format";

import { STATE_CHIP, type Brief } from "../briefs";

/**
 * One of the organisation's Briefs in its list (REQ-DIR-05), a card under its niche's photograph band (D-67): the title linking to the
 * Brief's page, one meta line (niche, county), one status mark (In review, Published, Not approved, Closed; docs/spec/07
 * item 2: at most two) and, at the foot, the proposals answering it and the deadline.
 */
export function BriefItem({ brief, href, county, band }: { brief: Brief; href: string; county: string | null; band?: ReactNode }) {
  const t = useTranslations("briefs");
  const locale = useLocale();
  const titleId = `brief-${brief.id}-title`;
  return (
    <ItemCard
      band={band}
      aria-labelledby={titleId}
      data-brief={brief.id}
      data-state={brief.state}
      title={brief.title}
      titleId={titleId}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4">
          {brief.niche ? <span>{brief.niche.label}</span> : null}
          <span>{county ?? t("anywhere")}</span>
        </span>
      }
      chips={[
        <Chip key="state" kind={STATE_CHIP[brief.state]}>
          {t(`state.${brief.state}`)}
        </Chip>,
      ]}
      footNote={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span data-proposals={brief.proposal_count}>{t("proposals", { count: brief.proposal_count })}</span>
          <span>{brief.deadline ? t("deadline", { date: formatCalendarDate(locale, brief.deadline) }) : t("noDeadline")}</span>
        </span>
      }
    />
  );
}
