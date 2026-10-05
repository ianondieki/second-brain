import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { Citations } from "@/components/problem/Citations";
import { formatConfidence, formatMoment, problemHref } from "@/components/problem/problem";
import { CompaniesIcon, InfoIcon, PencilIcon } from "@/components/ui/icons";
import { BackLink } from "@/components/ui/BackLink";
import { Badge } from "@/components/ui/Badge";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { Section } from "@/components/ui/Section";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../../../AdminShell";
import { staffContext } from "../../../staff";
import { getReview } from "../../data";
import { Decision } from "../../Decision";
import { PageStepUp } from "../../PageStepUp";
import { nicheLabel, RESEARCH_PATH } from "../../research";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminResearch");
  return { title: t("review.pageTitle") };
}

/**
 * One research card under review (REQ-RES-01; docs/spec/06 6.5 "mandatory moderator approval"; D-45): the card as it
 * would be published, every cited source with its verbatim quote, the organisations it names with the checklist,
 * and the decision. A card that is no longer a candidate (decided, or never one) reads the same as an unknown id.
 */
export default async function ReviewPage({ params }: PageProps<"/admin/research/candidates/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const t = await getTranslations("adminResearch");
  const back = (
    <BackLink href={RESEARCH_PATH}>{t("review.back")}</BackLink>
  );
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current="research">
      {back}
      {children}
    </AdminShell>
  );
  const empty = (sentence: string, action: string, href: string) =>
    shell(
      <>
        <PageHeader title={t("review.pageTitle")} focusable />
        <div className="mt-6">
          <EmptyState sentence={sentence} action={action} href={href} />
        </div>
      </>,
    );
  if (role !== "admin") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (!isUuid(id)) return empty(t("review.gone"), t("review.goneAction"), RESEARCH_PATH);

  const loaded = await getReview(id);
  if (loaded.kind === "forbidden") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  const strings = await clientStrings(["adminResearch"]);
  if (loaded.kind === "stepUp") {
    return shell(
      <>
        <PageHeader title={t("review.pageTitle")} focusable />
        <div className="mt-6">
          <ClientStrings strings={strings}>
            <PageStepUp />
          </ClientStrings>
        </div>
      </>,
    );
  }
  const { candidate, niches } = loaded.data;
  if (!candidate) return empty(t("review.gone"), t("review.goneAction"), RESEARCH_PATH);

  const locale = await getLocale();
  const tp = await getTranslations("problem");
  const confidence = formatConfidence(locale, candidate.confidence);
  const niche = nicheLabel(candidate.niche, niches);
  const region = tp("country", { country: candidate.country });
  const named = candidate.named_orgs.length > 0;

  return shell(
    <article aria-labelledby="card-title" className="flex flex-col gap-12">
      <PageHeader titleId="card-title" focusable title={candidate.title}>
        {/* How it was drafted, under the title (not a label above it). */}
        <p className="mt-3">
          <Badge tone="accent" icon={candidate.seeded_example ? <InfoIcon /> : <PencilIcon />}>
            {candidate.seeded_example ? t("queue.seeded") : t("queue.aiDrafted")}
          </Badge>
        </p>
        <p className="mt-4 max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink">{candidate.statement}</p>
        <DescriptionList className="mt-6">
          <Description label={t("review.affected")}>{candidate.affected_group || "–"}</Description>
          {niche ? <Description label={t("review.niche")}>{niche}</Description> : null}
          <Description label={t("review.region")}>
            {candidate.county_code ? tp("regionCounty", { county: candidate.county_code, country: region }) : region}
          </Description>
          {confidence ? (
            <Description label={t("review.confidence")}>{t("review.confidenceValue", { value: confidence })}</Description>
          ) : null}
          <Description label={t("review.drafted")}>{formatMoment(locale, candidate.created_at)}</Description>
        </DescriptionList>
      </PageHeader>

      <Section title={t("review.sourcesHeading")} headingId="sources" description={t("review.sourcesLead")}>
        <Citations sources={candidate.sources} labelledBy="sources" />
      </Section>

      {named ? (
        // The screen's one panel: what must be checked before a card naming an organisation is published.
        <Panel as="section" aria-labelledby="checklist" className="flex flex-col gap-4">
          <h2 id="checklist" className="inline-flex items-center gap-2 text-lg text-ink">
            <CompaniesIcon className="size-5 shrink-0" />
            {t("review.checklistHeading")}
          </h2>
          <div>
            <h3 className="text-sm font-medium text-ink-soft">{t("review.namedOrgs")}</h3>
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {candidate.named_orgs.map((name) => (
                <li key={name} className="font-semibold [overflow-wrap:anywhere] text-ink">
                  {name}
                </li>
              ))}
            </ul>
          </div>
          {/* The checklist wording comes from the API verbatim (D-45: a placeholder until the G2 legal pack). */}
          <ul className="flex max-w-[65ch] list-disc flex-col gap-2 pl-5 text-ink" data-checklist="">
            {candidate.checklist.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {/* The decision is what the card needs from the admin now: raised, as on a moderation case. */}
      <Section
        title={t("review.decisionHeading")}
        headingId="decision"
        description={t("review.decisionLead")}
        className="rounded-panel border border-line bg-field p-5 shadow-card sm:p-6"
      >
        <ClientStrings strings={strings}>
          <Decision
            problemId={candidate.id}
            needsChecklist={named}
            checklist={candidate.checklist}
            publicHref={problemHref(candidate.id)}
            researchHref={RESEARCH_PATH}
          />
        </ClientStrings>
      </Section>
    </article>,
  );
}
