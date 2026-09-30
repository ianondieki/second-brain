import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { formatDate, formatMoment } from "@/components/problem/problem";
import { standaloneLinkClass } from "@/components/ui/Button";
import { InfoIcon } from "@/components/ui/icons";

import { AdminShell } from "../../AdminShell";
import { caseHref } from "../../moderation/moderation";
import { PageStepUp } from "../../research/PageStepUp";
import { staffContext } from "../../staff";
import { stepUpStrings } from "../../strings";
import { ClaimChip } from "../ClaimRow";
import { CLAIMS_PATH, orgName, slaState } from "../claims";
import { getClaim } from "../data";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminClaims");
  return { title: t("detail.pageTitle") };
}

/**
 * One organisation claim, read only (REQ-DIR-03 queue; docs/spec/06 6.2): the review time left, the claimant and both
 * proofs, the E2 evidence (the registration number, KRA PIN and the claimant's address appear on this page only, never
 * in the queue), the organisation, its other open claims and any moderation cases. The prototype decides no claim: one
 * sentence says so and there are no decision buttons.
 */
export default async function ClaimPage({ params }: PageProps<"/admin/claims/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const t = await getTranslations("adminClaims");
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current="claims">
      <p className="-mt-2 mb-4">
        <Link href={CLAIMS_PATH} className={standaloneLinkClass}>
          {t("detail.back")}
        </Link>
      </p>
      {children}
    </AdminShell>
  );
  const plain = (children: ReactNode) =>
    shell(
      <>
        <h1 tabIndex={-1} className="text-xl text-ink focus:outline-none lg:text-2xl">
          {t("detail.pageTitle")}
        </h1>
        <div className="mt-6">{children}</div>
      </>,
    );
  const gone = () =>
    plain(<EmptyState sentence={t("detail.gone")} action={t("detail.goneAction")} href={CLAIMS_PATH} />);
  if (role !== "admin")
    return plain(<EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href="/admin" />);
  if (!isUuid(id)) return gone();

  const loaded = await getClaim(id);
  if (loaded.kind === "forbidden") {
    return plain(<EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href="/admin" />);
  }
  if (loaded.kind === "stepUp") {
    return plain(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }
  const claim = loaded.data;
  if (!claim) return gone();

  const locale = await getLocale();
  const kinds = await getTranslations("orgKind");
  const name = orgName(claim.org);
  const sla = slaState(claim.sla);
  const moment = (iso: string) => formatMoment(locale, iso);
  const given = (value: string | null) => value?.trim() || t("detail.notGiven");
  const closed = claim.status === "approved" || claim.status === "rejected" || claim.status === "withdrawn";

  return shell(
    <article aria-labelledby="claim-title" className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        <h1
          id="claim-title"
          tabIndex={-1}
          className="text-xl [overflow-wrap:anywhere] text-ink focus:outline-none lg:text-2xl"
        >
          {name ?? t("unnamed", { id: claim.org.id })}
        </h1>
        {name ? null : <p className="max-w-[60ch] text-ink-soft">{t("unnamedNote")}</p>}
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          <li>
            <ClaimChip claim={claim} />
          </li>
          <li className="font-medium text-ink">{t(`level.${claim.level}`)}</li>
        </ul>
        <p
          className="mt-2 flex max-w-[65ch] items-start gap-2 rounded-control bg-jacaranda-wash px-4 py-3 text-ink"
          data-read-only=""
        >
          <InfoIcon className="mt-0.5 size-5 shrink-0 text-jacaranda" />
          <span>{t("detail.readOnly")}</span>
        </p>
      </header>

      <Section id="claim" heading={t("detail.claimHeading")}>
        <Row label={t("detail.status")}>{t(`status.${claim.status}`)}</Row>
        {sla && claim.sla ? (
          <Row label={t("detail.reviewTime")}>{t("sla.dueBy", { date: formatDate(locale, claim.sla.due_on) })}</Row>
        ) : null}
        <Row label={t("detail.filed")}>{moment(claim.created_at)}</Row>
        <Row label={t("detail.updated")}>{moment(claim.updated_at)}</Row>
        {closed && claim.decided_at ? <Row label={t("detail.closed")}>{moment(claim.decided_at)}</Row> : null}
      </Section>

      <Section id="claimant" heading={t("detail.claimantHeading")}>
        <Row label={t("detail.name")}>{claim.claimant.display_name}</Row>
        <Row label={t("detail.email")}>{claim.email_address}</Row>
        <Row label={t("detail.domain")}>{claim.domain}</Row>
        <Row label={t("detail.domainOfficial")}>{claim.domain_is_official ? t("detail.yes") : t("detail.no")}</Row>
      </Section>

      <Section id="checks" heading={t("detail.checksHeading")}>
        <Row label={t("detail.emailCode")}>
          {claim.otp_verified_at
            ? t("detail.confirmedOn", { date: moment(claim.otp_verified_at) })
            : t("detail.notConfirmed")}
          <span className="mt-0.5 block text-sm text-ink-soft">
            {t("detail.codeUse", { attempts: claim.otp_attempts, reissues: claim.otp_reissues })}
          </span>
        </Row>
        <Row label={t("detail.dns")}>
          {claim.dns_verified_at ? t("detail.foundOn", { date: moment(claim.dns_verified_at) }) : t("detail.notFound")}
        </Row>
      </Section>

      {claim.level === "e2" ? (
        <Section id="evidence" heading={t("detail.evidenceHeading")} lead={t("detail.evidenceLead")}>
          <Row label={t("detail.registrationNo")}>
            <span data-pii="registration_no">{given(claim.registration_no)}</span>
          </Row>
          <Row label={t("detail.cr12Date")}>
            {claim.cr12_date ? formatDate(locale, claim.cr12_date) : t("detail.notGiven")}
          </Row>
          <Row label={t("detail.kraPin")}>
            <span data-pii="kra_pin">{given(claim.kra_pin)}</span>
          </Row>
          <Row label={t("detail.sectorRegister")}>{given(claim.sector_register)}</Row>
          <Row label={t("detail.publicEntity")}>
            {claim.public_entity_requested ? t("detail.requested") : t("detail.notRequested")}
          </Row>
          <Row label={t("detail.documents")}>
            {claim.document_count > 0
              ? t("detail.documentCount", { count: claim.document_count })
              : t("detail.noDocuments")}
            <span className="mt-0.5 block text-sm text-ink-soft">{t("detail.documentsNote")}</span>
          </Row>
        </Section>
      ) : null}

      <Section id="organisation" heading={t("detail.orgHeading")}>
        {claim.org.kind ? <Row label={t("detail.kind")}>{kinds(claim.org.kind)}</Row> : null}
        {claim.org.verification ? (
          <Row label={t("detail.verification")}>{t(`verification.${claim.org.verification}`)}</Row>
        ) : null}
        <Row label={t("detail.officialDomains")}>
          {claim.official_domains.length > 0 ? claim.official_domains.join(", ") : t("detail.none")}
        </Row>
        <Row label={t("detail.verifiedDomain")}>{claim.verified_domain ?? t("detail.none")}</Row>
      </Section>

      {claim.other_claims.length > 0 ? (
        <section aria-labelledby="others" className="flex flex-col gap-3">
          <h2 id="others" className="text-lg text-ink">
            {t("detail.othersHeading")}
          </h2>
          <ul className="flex flex-col">
            {claim.other_claims.map((other) => (
              <li
                key={other.id}
                className="flex flex-col gap-0.5 border-t border-line py-3 first:border-t-0 first:pt-0"
              >
                <span className="font-medium text-ink">{t("by", { name: other.claimant.display_name })}</span>
                <span className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
                  <span className="[overflow-wrap:anywhere]">{other.domain}</span>
                  <span>{t(`level.${other.level}`)}</span>
                  <span>{t(`status.${other.status}`)}</span>
                  <span>{t("filed", { date: moment(other.created_at) })}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {claim.cases.length > 0 ? (
        <section aria-labelledby="cases" className="flex flex-col gap-3">
          <h2 id="cases" className="text-lg text-ink">
            {t("detail.casesHeading")}
          </h2>
          <ul className="flex flex-col">
            {claim.cases.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-x-4 border-t border-line first:border-t-0">
                <Link href={caseHref(item.id)} className={standaloneLinkClass}>
                  {t("detail.caseLine", { date: moment(item.created_at) })}
                </Link>
                <span className="text-sm text-ink-soft">{t(`caseStatus.${item.status}`)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {closed && (claim.reviewed_by || claim.decision_reason) ? (
        <Section id="decision" heading={t("detail.decisionHeading")}>
          {claim.reviewed_by ? <Row label={t("detail.reviewedBy")}>{claim.reviewed_by.display_name}</Row> : null}
          {claim.decision_reason ? <Row label={t("detail.reason")}>{claim.decision_reason}</Row> : null}
        </Section>
      ) : null}
    </article>,
  );
}

function Section({ id, heading, lead, children }: { id: string; heading: string; lead?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div>
        <h2 id={id} className="text-lg text-ink">
          {heading}
        </h2>
        {lead ? <p className="mt-1 max-w-[60ch] text-sm text-ink-soft">{lead}</p> : null}
      </div>
      <dl className="grid gap-x-8 gap-y-3 border-t border-line pt-4 sm:grid-cols-[14rem_1fr]">{children}</dl>
    </section>
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
