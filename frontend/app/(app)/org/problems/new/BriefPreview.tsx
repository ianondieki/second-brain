"use client";

import { useStrings } from "@/components/ClientStrings";
import { formatCalendarDate } from "@/lib/format";

import type { BriefDraft, BudgetBand } from "../../brief-draft";
import type { NicheGroup } from "./BriefForm";
import { BriefPreviewView } from "./BriefPreviewView";

/** The niche's name as Discover shows it ("Financial services › Microfinance & SACCOs"), from the form's tree. */
function nicheLabel(niches: readonly NicheGroup[], id: string): string | null {
  for (const parent of niches) {
    if (parent.id === id) return parent.name;
    const child = parent.children.find((c) => c.id === id);
    if (child) return `${parent.name} › ${child.name}`;
  }
  return null;
}

export interface BriefPreviewProps {
  draft: BriefDraft;
  orgName: string;
  niches: readonly NicheGroup[];
  counties: readonly { id: string; label: string }[];
  bands: readonly BudgetBand[];
  locale: string;
}

/**
 * The live preview of how the Brief reads on Discover (BriefPreviewView), from the draft as it is typed. Loaded on
 * the form's first edit (BriefForm), so the page's first load carries none of it (REQ-UX-05's 150 KB). Words from the
 * server-formatted `briefForm` strings.
 */
export function BriefPreview({ draft, orgName, niches, counties, bands, locale }: BriefPreviewProps) {
  const t = useStrings("briefForm");
  const band = bands.find((b) => b.code === draft.band)?.label;
  const day = /^\d{4}-\d{2}-\d{2}$/.test(draft.deadline) ? formatCalendarDate(locale, draft.deadline) : null;
  return (
    <BriefPreviewView
      words={{
        heading: t("preview.title"),
        title: draft.title.trim() || t("preview.untitled"),
        niche: nicheLabel(niches, draft.niche),
        place: counties.find((c) => c.id === draft.county)?.label ?? t("countyAny"),
        postedBy: t("preview.postedBy", { org: orgName }),
        statement: draft.statement.trim() || t("preview.statement"),
        budget: band ? t("preview.budget", { value: band }) : t("preview.noBudget"),
        deadline: day ? t("preview.deadline", { date: day }) : t("preview.noDeadline"),
        note: t("preview.note"),
      }}
    />
  );
}

export default BriefPreview;
