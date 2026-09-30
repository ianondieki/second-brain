import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { InfoIcon, PencilIcon } from "@/components/ui/icons";

import { Citations } from "./Citations";
import { formatConfidence, problemLabel, type ProblemDetail } from "./problem";

/**
 * A published problem card (REQ-RES-02; docs/spec/06 6.5 ProblemCard): its label ("AI-drafted, human-reviewed on
 * <date>", a seeded example, or "Developer-reported"), title, statement, who is affected, niche, region, confidence,
 * the organisations it names, and every cited source with its verbatim quote. The page supplies the heading level's
 * context: the title is the page's h1. P12-F's Discover links here (components/problem/problem.ts problemHref).
 */
export async function ProblemCard({ problem }: { problem: ProblemDetail }) {
  const t = await getTranslations("problem");
  const locale = await getLocale();
  const label = problemLabel(problem, locale);
  const confidence = formatConfidence(locale, problem.confidence);
  const country = t("country", { country: problem.country });
  const LabelIcon = label?.key === "aiDrafted" ? PencilIcon : InfoIcon;

  return (
    <article aria-labelledby="problem-title" data-problem={problem.id} className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        {label ? (
          <p data-label={label.key} className="inline-flex items-start gap-1.5 text-sm font-semibold text-jacaranda">
            <LabelIcon className="mt-0.5 size-4 shrink-0" />
            <span>
              {label.key === "developer" ? t("label.developer") : t(`label.${label.key}`, { date: label.date })}
            </span>
          </p>
        ) : null}
        <h1 id="problem-title" className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
          {problem.title}
        </h1>
        <p className="max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
        <dl className="mt-3 grid gap-x-8 gap-y-3 border-t border-line pt-5 sm:grid-cols-[minmax(9rem,auto)_1fr]">
          {problem.affected_group ? <Row label={t("affected")}>{problem.affected_group}</Row> : null}
          {problem.niche ? <Row label={t("niche")}>{problem.niche.label}</Row> : null}
          <Row label={t("region")}>
            {problem.county_code ? t("regionCounty", { county: problem.county_code, country }) : country}
          </Row>
          {confidence ? <Row label={t("confidence")}>{t("confidenceValue", { value: confidence })}</Row> : null}
          {problem.named_orgs.length > 0 ? (
            <Row label={t("namedOrgs")}>
              <ul className="flex flex-col gap-1">
                {problem.named_orgs.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </Row>
          ) : null}
        </dl>
      </header>

      {problem.citations.length > 0 ? (
        <section aria-labelledby="problem-sources" className="flex flex-col gap-4">
          <div>
            <h2 id="problem-sources" className="text-lg text-ink">
              {t("sourcesHeading")}
            </h2>
            <p className="mt-1 text-ink-soft">{t("sourcesCount", { count: problem.citations.length })}</p>
          </div>
          <Citations sources={problem.citations} labelledBy="problem-sources" />
        </section>
      ) : null}
    </article>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm font-medium text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere] text-ink">{children}</dd>
    </div>
  );
}
