import { useLocale, useTranslations } from "next-intl";

import { DemoBadge } from "./DemoBadge";

import { listedProblemLabel, type ListedProblem } from "./problem";

/**
 * A listed problem's provenance label as plain words ("Developer-reported", "AI-drafted, human-reviewed on 30 Sep
 * 2026"), for a row's meta line on Discover and Home; `data-label` names it for tests. Nothing when it has none.
 */
export function ProblemLabelText({ problem }: { problem: ListedProblem }) {
  const t = useTranslations("problem");
  const locale = useLocale();
  const label = listedProblemLabel(problem, locale);
  if (!label) return null;
  const text =
    label.key === "api"
      ? label.text
      : label.key === "developer"
        ? t("label.developer")
        : label.key === "org_brief"
          ? t("label.org_brief", { org: label.org })
          : t(`label.${label.key}`, { date: label.date });
  // A seeded example: the small "Demo data" badge, the sentence on demand (D-52).
  if (label.key === "seeded") return <DemoBadge label={t("label.demoBadge")} sentence={text} data-label={label.key} />;
  return <span data-label={label.key}>{text}</span>;
}
