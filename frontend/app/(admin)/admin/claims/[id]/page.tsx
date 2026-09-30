import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { formatDate, formatMoment } from "@/components/problem/problem";
import { Callout } from "@/components/ui/Callout";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { PageHeader } from "@/components/ui/PageHeader";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { BackLink } from "@/components/ui/BackLink";

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
      <BackLink href={CLAIMS_PATH}>{t("detail.back")}</BackLink>
      {children}
    </AdminShell>
  );
  const plain = (children: ReactNode) =>
    shell(
      <>
        <PageHeader title={t("detail.pageTitle")} focusable />
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
    <article aria-labelledby="claim-title" className="flex flex-col gap-12">
      <PageHeader
        titleId="claim-title"
        focusable
        title={name ?? t("unnamed", { id: claim.org.id })}
        lead={name ? undefined : t("unnamedNote")}
      >
        <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          <li>
            <ClaimChip claim={claim} />
          </li>
          <li className="font-medium text-ink">{t(`level.${claim.level}`)}</li>
        </ul>
        <Callout className="mt-5 max-w-[65ch]" data-read-only="">
          <p>{t("detail.readOnly")}</p>
        </Callout>
      </PageHeader>

      <Facts id="claim" heading={t("detail.claimHeading")}>
        <Description label={t("detail.status")}>{t(`status.${claim.status}`)}</Description>
        {sla && claim.sla ? (
          <Description label={t("detail.reviewTime")}>{t("sla.dueBy", { date: formatDate(locale, claim.sla.due_on) })}</Description>
        ) : null}
        <Description label={t("detail.filed")}>{moment(claim.created_at)}</Description>
        <Description label={t("detail.updated")}>{moment(claim.updated_at)}</Description>
        {closed && claim.decided_at ? <Description label={t("detail.closed")}>{moment(claim.decided_at)}</Description> : null}
      </Facts>

      <Facts id="claimant" heading={t("detail.claimantHeading")}>
        <Description label={t("detail.name")}>{claim.claimant.display_name}</Description>
        <Description label={t("detail.email")}>{claim.email_address}</Description>
        <Description label={t("detail.domain")}>{claim.domain}</Description>
        <Description label={t("detail.domainOfficial")}>{claim.domain_is_official ? t("detail.yes") : t("detail.no")}</Description>
      </Facts>

      <Facts id="checks" heading={t("detail.checksHeading")}>
        <Description label={t("detail.emailCode")}>
          {claim.otp_verified_at
            ? t("detail.confirmedOn", { date: moment(claim.otp_verified_at) })
            : t("detail.notConfirmed")}
          <span className="mt-0.5 block text-sm text-ink-soft">
            {t("detail.codeUse", { attempts: claim.otp_attempts, reissues: claim.otp_reissues })}
          </span>
        </Description>
        <Description label={t("detail.dns")}>
          {claim.dns_verified_at ? t("detail.foundOn", { date: moment(claim.dns_verified_at) }) : t("detail.notFound")}
        </Description>
      </Facts>

      {claim.level === "e2" ? (
        <Facts id="evidence" heading={t("detail.evidenceHeading")} lead={t("detail.evidenceLead")}>
          <Description label={t("detail.registrationNo")}>
            <span data-pii="registration_no">{given(claim.registration_no)}</span>
          </Description>
          <Description label={t("detail.cr12Date")}>
            {claim.cr12_date ? formatDate(locale, claim.cr12_date) : t("detail.notGiven")}
          </Description>
          <Description label={t("detail.kraPin")}>
            <span data-pii="kra_pin">{given(claim.kra_pin)}</span>
          </Description>
          <Description label={t("detail.sectorRegister")}>{given(claim.sector_register)}</Description>
          <Description label={t("detail.publicEntity")}>
            {claim.public_entity_requested ? t("detail.requested") : t("detail.notRequested")}
          </Description>
          <Description label={t("detail.documents")}>
            {claim.document_count > 0
              ? t("detail.documentCount", { count: claim.document_count })
              : t("detail.noDocuments")}
            <span className="mt-0.5 block text-sm text-ink-soft">{t("detail.documentsNote")}</span>
          </Description>
        </Facts>
      ) : null}

      <Facts id="organisation" heading={t("detail.orgHeading")}>
        {claim.org.kind ? <Description label={t("detail.kind")}>{kinds(claim.org.kind)}</Description> : null}
        {claim.org.verification ? (
          <Description label={t("detail.verification")}>{t(`verification.${claim.org.verification}`)}</Description>
        ) : null}
        <Description label={t("detail.officialDomains")}>
          {claim.official_domains.length > 0 ? claim.official_domains.join(", ") : t("detail.none")}
        </Description>
        <Description label={t("detail.verifiedDomain")}>{claim.verified_domain ?? t("detail.none")}</Description>
      </Facts>

      {claim.other_claims.length > 0 ? (
        <Section title={t("detail.othersHeading")} headingId="others">
          <RowList>
            {claim.other_claims.map((other) => (
              <Row
                key={other.id}
                title={t("by", { name: other.claimant.display_name })}
                meta={
                  <span className="flex flex-wrap gap-x-4 gap-y-1">
                    <span className="[overflow-wrap:anywhere]">{other.domain}</span>
                    <span>{t(`level.${other.level}`)}</span>
                    <span>{t(`status.${other.status}`)}</span>
                    <span>{t("filed", { date: moment(other.created_at) })}</span>
                  </span>
                }
              />
            ))}
          </RowList>
        </Section>
      ) : null}

      {claim.cases.length > 0 ? (
        <Section title={t("detail.casesHeading")} headingId="cases">
          <RowList>
            {claim.cases.map((item) => (
              <Row
                key={item.id}
                title={t("detail.caseLine", { date: moment(item.created_at) })}
                href={caseHref(item.id)}
                meta={t(`caseStatus.${item.status}`)}
              />
            ))}
          </RowList>
        </Section>
      ) : null}

      {closed && (claim.reviewed_by || claim.decision_reason) ? (
        <Facts id="decision" heading={t("detail.decisionHeading")}>
          {claim.reviewed_by ? <Description label={t("detail.reviewedBy")}>{claim.reviewed_by.display_name}</Description> : null}
          {claim.decision_reason ? <Description label={t("detail.reason")}>{claim.decision_reason}</Description> : null}
        </Facts>
      ) : null}
    </article>,
  );
}

/** A titled group of the claim's facts: a Section with one DescriptionList (the page's one label column width). */
function Facts({ id, heading, lead, children }: { id: string; heading: string; lead?: string; children: ReactNode }) {
  return (
    <Section title={heading} headingId={id} description={lead}>
      <DescriptionList>{children}</DescriptionList>
    </Section>
  );
}
