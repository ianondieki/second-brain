import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Lattice } from "@/components/ui/Lattice";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { InfoIcon, PencilIcon } from "@/components/ui/icons";
import { Section } from "@/components/ui/Section";

import { Citations } from "./Citations";
import { formatConfidence, problemLabel, type ProblemDetail } from "./problem";

/**
 * A published problem card (REQ-RES-02; docs/spec/06 6.5 ProblemCard): its label ("AI-drafted, human-reviewed on
 * <date>", a seeded example, or "Developer-reported"), title, statement, who is affected, niche, region, confidence,
 * the organisations it names, and every cited source with its verbatim quote. The page supplies the heading level's
 * context: the title is the page's h1. P12-F's Discover links here (components/problem/problem.ts problemHref).
 */
export async function ProblemCard({ problem, action }: { problem: ProblemDetail; action?: ReactNode }) {
  const t = await getTranslations("problem");
  const locale = await getLocale();
  const label = problemLabel(problem, locale);
  const confidence = formatConfidence(locale, problem.confidence);
  const country = t("country", { country: problem.country });
  const LabelIcon = label?.key === "aiDrafted" ? PencilIcon : InfoIcon;

  return (
    <article aria-labelledby="problem-title" data-problem={problem.id} className="flex flex-col gap-10">
      {/* The card itself: a lattice-edged sheet (the look of the certificate and /verify), the facts under a rule. */}
      <Card padding="none" className="overflow-hidden">
        <Lattice />
        <header className="flex flex-col gap-3 p-5 sm:p-8">
        <h1 id="problem-title" className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
          {problem.title}
        </h1>
        {/* The card's label (docs/spec/09 AI labels) under the title as a Badge: no eyebrow above a heading. Neutral:
            the accent is kept for "act here or you are here" (p16-design-system.md, principle 3). */}
        {label ? (
          <p>
            <Badge data-label={label.key} tone="neutral" icon={<LabelIcon />}>
              {label.key === "developer" ? t("label.developer") : t(`label.${label.key}`, { date: label.date })}
            </Badge>
          </p>
        ) : null}
        <p className="max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
        {/* The page's one action, when the reader can take it (a developer: start a proposal from it). */}
        {action ? <div className="mt-2">{action}</div> : null}
        <DescriptionList className="mt-3 border-t border-line pt-5">
          {problem.affected_group ? <Description label={t("affected")}>{problem.affected_group}</Description> : null}
          {problem.niche ? <Description label={t("niche")}>{problem.niche.label}</Description> : null}
          <Description label={t("region")}>
            {problem.county_code ? t("regionCounty", { county: problem.county_code, country }) : country}
          </Description>
          {confidence ? (
            <Description label={t("confidence")}>{t("confidenceValue", { value: confidence })}</Description>
          ) : null}
          {problem.named_orgs.length > 0 ? (
            <Description label={t("namedOrgs")}>
              <ul className="flex flex-col gap-1">
                {problem.named_orgs.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </Description>
          ) : null}
        </DescriptionList>
        </header>
      </Card>

      {problem.citations.length > 0 ? (
        <Section
          title={t("sourcesHeading")}
          headingId="problem-sources"
          description={t("sourcesCount", { count: problem.citations.length })}
        >
          <Citations sources={problem.citations} labelledBy="problem-sources" />
        </Section>
      ) : null}
    </article>
  );
}
