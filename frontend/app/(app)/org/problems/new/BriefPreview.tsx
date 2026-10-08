"use client";

import { useStrings } from "@/components/ClientStrings";
import { formatCalendarDate } from "@/lib/format";

import type { BriefDraft, BudgetBand } from "../../brief-draft";
import type { NicheGroup } from "./BriefForm";

/** The niche's name as Discover shows it ("Financial services › Microfinance & SACCOs"), from the form's tree. */
function nicheLabel(niches: readonly NicheGroup[], id: string): string | null {
  for (const parent of niches) {
    if (parent.id === id) return parent.name;
    const child = parent.children.find((c) => c.id === id);
    if (child) return `${parent.name} › ${child.name}`;
  }
  return null;
}

/**
 * How the Brief will read on Discover (D-67, P25), live as the form is filled in: the card a developer meets, with
 * the title, the niche and place, "Posted by" the organisation, the statement (three lines), and the budget band and
 * deadline. Decorative for assistive technology apart from its heading: the form's own fields carry every word, so
 * the preview is not read twice. Words from the server-formatted `briefForm` strings; no photograph (the browser
 * would fetch it as the niche changes).
 */
export function BriefPreview({
  draft,
  orgName,
  niches,
  counties,
  bands,
  locale,
}: {
  draft: BriefDraft;
  orgName: string;
  niches: readonly NicheGroup[];
  counties: readonly { id: string; label: string }[];
  bands: readonly BudgetBand[];
  locale: string;
}) {
  const t = useStrings("briefForm");
  const niche = nicheLabel(niches, draft.niche);
  const place = counties.find((c) => c.id === draft.county)?.label ?? t("countyAny");
  const band = bands.find((b) => b.code === draft.band)?.label;
  const day = /^\d{4}-\d{2}-\d{2}$/.test(draft.deadline) ? formatCalendarDate(locale, draft.deadline) : null;
  return (
    <section aria-labelledby="brief-preview-heading" className="brief-preview" data-brief-preview="">
      <h2 id="brief-preview-heading" className="page-eyebrow">
        {t("preview.title")}
      </h2>
      <div aria-hidden="true" className="brief-preview-card">
        <div className="niche-band niche-band-lattice h-10 rounded-none" />
        <div className="flex flex-col gap-2 p-4">
          <p className="text-[1.0625rem] leading-snug font-semibold [overflow-wrap:anywhere] text-ink" data-preview="title">
            {draft.title.trim() || t("preview.untitled")}
          </p>
          <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
            {niche ? <span>{niche}</span> : null}
            <span>{place}</span>
          </p>
          <p className="text-sm font-medium text-ink">{t("preview.postedBy", { org: orgName })}</p>
          <p className="line-clamp-3 [overflow-wrap:anywhere] text-ink-soft" data-preview="statement">
            {draft.statement.trim() || t("preview.statement")}
          </p>
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm font-semibold text-ink tabular-nums">
            <span>{band ? t("preview.budget", { band }) : t("preview.noBudget")}</span>
            <span>{day ? t("preview.deadline", { date: day }) : t("preview.noDeadline")}</span>
          </p>
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-soft">{t("preview.note")}</p>
    </section>
  );
}
