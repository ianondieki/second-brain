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
        <h1 tabIndex={-1} className="text-xl text-ink focus:outline-none lg:text-2xl">
          {t("review.pageTitle")}
        </h1>
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
        <h1 tabIndex={-1} className="text-xl text-ink focus:outline-none lg:text-2xl">
          {t("review.pageTitle")}
        </h1>
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
    <article aria-labelledby="card-title" className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-jacaranda">
          {candidate.seeded_example ? <InfoIcon className="size-4" /> : <PencilIcon className="size-4" />}
          {candidate.seeded_example ? t("queue.seeded") : t("queue.aiDrafted")}
        </p>
        <h1 id="card-title" tabIndex={-1} className="text-xl [overflow-wrap:anywhere] text-ink focus:outline-none lg:text-2xl">
          {candidate.title}
        </h1>
        <p className="max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink">{candidate.statement}</p>
        <dl className="mt-3 grid gap-x-8 gap-y-3 border-t border-line pt-5 sm:grid-cols-[minmax(9rem,auto)_1fr]">
          <Row label={t("review.affected")}>{candidate.affected_group || "–"}</Row>
          {niche ? <Row label={t("review.niche")}>{niche}</Row> : null}
          <Row label={t("review.region")}>
            {candidate.county_code ? tp("regionCounty", { county: candidate.county_code, country: region }) : region}
          </Row>
          {confidence ? (
            <Row label={t("review.confidence")}>{t("review.confidenceValue", { value: confidence })}</Row>
          ) : null}
          <Row label={t("review.drafted")}>{formatMoment(locale, candidate.created_at)}</Row>
        </dl>
      </header>

      <section aria-labelledby="sources" className="flex flex-col gap-4">
        <div>
          <h2 id="sources" className="text-lg text-ink">
            {t("review.sourcesHeading")}
          </h2>
          <p className="mt-1 max-w-[60ch] text-ink-soft">{t("review.sourcesLead")}</p>
        </div>
        <Citations sources={candidate.sources} labelledBy="sources" />
      </section>

      {named ? (
        <section
          aria-labelledby="checklist"
          className="flex flex-col gap-4 rounded-panel border border-line bg-field px-4 py-5 sm:px-6"
        >
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
        </section>
      ) : null}

      <section aria-labelledby="decision" className="flex flex-col gap-4 border-t border-line pt-6">
        <div>
          <h2 id="decision" className="text-lg text-ink">
            {t("review.decisionHeading")}
          </h2>
          <p className="mt-1 max-w-[60ch] text-ink-soft">{t("review.decisionLead")}</p>
        </div>
        <ClientStrings strings={strings}>
          <Decision
            problemId={candidate.id}
            needsChecklist={named}
            checklist={candidate.checklist}
            publicHref={problemHref(candidate.id)}
            researchHref={RESEARCH_PATH}
          />
        </ClientStrings>
      </section>
    </article>,
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
