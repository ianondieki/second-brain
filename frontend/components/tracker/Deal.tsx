import { useLocale, useTranslations } from "next-intl";

import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { cn } from "@/components/ui/cn";

import { Chip, ChipMark } from "./Chip";
import {
  kesAmount,
  shortHash,
  type Agreement,
  type ChipKind,
  type Detail,
  type Endorsement,
  type Milestone,
  type MilestoneState,
  type Payment,
  type Signature,
} from "./model";
import { Day, Eat, useDay, useEat } from "./When";

// The deal's records as both parties see them (docs/spec/06 6.9; AC-TRACK-10): the agreement versions with their
// milestones, the signatures and the payments. Read-only: the buttons live in Actions.

/** Organisation roles the API names the contact person by (EngagementActorRole values have labels). */
const ROLES: ReadonlySet<string> = new Set(["owner", "admin", "reviewer", "signatory", "finance"]);

const MILESTONE_CHIP: Record<MilestoneState, ChipKind> = {
  PLANNED: "pending",
  IN_PROGRESS: "current",
  SUBMITTED_FOR_REVIEW: "current",
  ACCEPTED: "completed",
  CHANGES_REQUESTED: "onHold",
};

/** "KES 250,000" */
export function Kes({ minor, className }: { minor: number; className?: string }) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  return <span className={cn("tabular-nums", className)}>{t("kes", { amount: kesAmount(minor, locale) })}</span>;
}

/** The latest agreement version in full; earlier versions folded away. */
export function Agreements({ detail }: { detail: Pick<Detail, "agreements" | "endorsements"> }) {
  const t = useTranslations("tracker");
  if (detail.agreements.length === 0) return null;
  const sorted = [...detail.agreements].sort((a, b) => b.version - a.version);
  const [latest, ...earlier] = sorted;
  return (
    <Section title={t("agreement.title")} headingId="agreement-heading">
      {/* The agreement reads like a document: one white sheet with a hairline, its terms, then the milestone schedule. */}
      <div className="rounded-panel border border-line bg-field px-5 py-6 sm:px-8 sm:py-7">
      <AgreementVersion agreement={latest} endorsements={detail.endorsements} />
      {earlier.length > 0 ? (
        <details className="mt-6 border-t border-line pt-3">
          <summary className="flex min-h-11 cursor-pointer items-center font-semibold text-accent">
            {t("agreement.earlier", { count: earlier.length })}
          </summary>
          {earlier.map((agreement) => (
            <AgreementVersion
              key={agreement.id}
              agreement={agreement}
              endorsements={[]}
              className="mt-3 border-t border-line pt-4"
            />
          ))}
        </details>
      ) : null}
      </div>
    </Section>
  );
}

function AgreementVersion({
  agreement,
  endorsements,
  className,
}: {
  agreement: Agreement;
  endorsements: Endorsement[];
  className?: string;
}) {
  const t = useTranslations("tracker");
  const eat = useEat();
  const status: ChipKind = agreement.status === "signed" ? "completed" : agreement.status === "final" ? "current" : "pending";
  return (
    // No rule above the latest version: the rule belongs to lists (the milestones, the earlier versions).
    <article data-agreement={agreement.status} className={className}>
      <h3 className="flex flex-wrap items-center gap-x-4 gap-y-1 text-lg text-ink">
        {t("agreement.version", { version: agreement.version })}
        <Chip kind={status}>{t(`agreement.status.${agreement.status}`)}</Chip>
      </h3>
      <p className="mt-1 text-sm text-ink-soft">
        {t(`agreement.draftedBy.${agreement.drafted_by}`, { when: eat(agreement.created_at) })}
      </p>
      <DescriptionList className="mt-5 border-t border-line pt-5">
        <Description label={t("agreement.ipTerms")}>
          {agreement.ip_terms ? t(`ipTerms.${agreement.ip_terms}`) : t("agreement.notGiven")}
        </Description>
        <Description label={t("agreement.deemed")}>
          {agreement.deemed_acceptance_days === null
            ? t("agreement.notGiven")
            : agreement.deemed_acceptance_days === 0
              ? t("agreement.deemedNever")
              : t("agreement.deemedDays", { count: agreement.deemed_acceptance_days })}
        </Description>
        <Description label={t("agreement.exclusivity")}>{agreement.exclusivity ?? t("agreement.noExclusivity")}</Description>
      </DescriptionList>
      {agreement.milestones.length > 0 ? (
        <>
          <h4 className="mt-8 font-semibold text-ink">{t("milestone.title")}</h4>
          <ol className="mt-2 flex flex-col">
            {[...agreement.milestones]
              .sort((a, b) => a.seq - b.seq)
              .map((milestone) => (
                <li key={milestone.id} className="border-t border-line py-4">
                  <MilestoneRow
                    milestone={milestone}
                    endorsements={endorsements.filter((e) => e.milestone_id === milestone.id)}
                    live={agreement.status === "signed"}
                  />
                </li>
              ))}
          </ol>
          {/* The schedule's sum, under a firmer rule, as a statement of work closes. */}
          {agreement.milestones.length > 1 ? (
            <p data-milestone-total="" className="flex items-baseline justify-between gap-4 border-t-2 border-ink pt-3">
              <span className="font-semibold text-ink">{t("milestone.total")}</span>
              <Kes
                minor={agreement.milestones.reduce((sum, m) => sum + m.amount_kes_minor, 0)}
                className="font-display text-xl font-bold text-ink"
              />
            </p>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function MilestoneRow({
  milestone,
  endorsements,
  live,
}: {
  milestone: Milestone;
  endorsements: Endorsement[];
  live: boolean;
}) {
  const t = useTranslations("tracker");
  const eat = useEat();
  const day = useDay();
  return (
    <div data-milestone-row={milestone.seq} data-milestone-state={milestone.state}>
      <p className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="font-semibold text-ink">
          {t("milestone.name", { number: milestone.seq, deliverable: milestone.deliverable })}
        </span>
        <Kes minor={milestone.amount_kes_minor} className="font-display text-lg font-semibold text-ink" />
      </p>
      <p className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-soft">
        {live ? <Chip kind={MILESTONE_CHIP[milestone.state]}>{t(`milestone.state.${milestone.state}`)}</Chip> : null}
        <span>{t("milestone.due", { date: day(milestone.due_date) })}</span>
        <span>{t("milestone.window", { count: milestone.review_window_bd })}</span>
        {milestone.review_due_on ? (
          <span className="font-semibold text-ink">
            {t("milestone.reviewDue", { date: day(milestone.review_due_on) })}
          </span>
        ) : null}
      </p>
      {endorsements.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1 text-sm text-ink">
          {endorsements.map((e) => (
            <li key={e.id}>
              {t("milestone.endorsed", {
                party: t(`endorsements.by.${e.party}`),
                name: e.name ?? t("endorsements.platform"),
                method: t(`method.${e.method}`),
                when: eat(e.endorsed_at),
              })}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Who signed which document, when and with which second factor, with the fingerprint signed: grouped by the document
 * signed (its kind and fingerprint), each signer a block side by side from 640 px, as signatures close a contract.
 */
export function Signatures({ signatures }: { signatures: Signature[] }) {
  const t = useTranslations("tracker");
  if (signatures.length === 0) return null;
  const groups = new Map<string, Signature[]>();
  for (const s of signatures) {
    const key = `${s.document_kind}:${s.document_sha256}`;
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  return (
    <Section title={t("signature.title")} headingId="signatures-heading">
      <ul className="flex flex-col">
        {[...groups.entries()].map(([key, group]) => (
          <li key={key} className="border-t border-line py-5 first:border-t-0 first:pt-0 last:pb-0">
            <h3 className="font-semibold text-ink">{t(`document.${group[0].document_kind}`)}</h3>
            <ul className="mt-3 grid gap-3 sm:grid-cols-2">
              {group.map((s) => (
                <li key={s.id} data-signature={s.document_kind} className="flex gap-3">
                  <ChipMark kind="completed" className="mt-0.5 size-5 text-accent" />
                  <div className="min-w-0">
                    {/* Each signature names its document for a screen reader moving item by item. */}
                    <p className="sr-only">{t(`document.${s.document_kind}`)}</p>
                    <p className="text-sm text-ink">
                      {t("signature.by", {
                        name: s.signer_name ?? t("endorsements.platform"),
                        party: t(`party.${s.party}`),
                        method: t(`method.${s.step_up_method}`),
                      })}
                    </p>
                    <p className="mt-1 flex flex-wrap gap-x-4 text-sm text-ink-soft">
                      <Eat iso={s.signed_at} />
                      <span className="tabular-nums">{t("fingerprint", { hash: shortHash(s.document_sha256) })}</span>
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** Payments the organisation recorded and the developer confirmed (the platform never holds or moves money). */
export function Payments({ payments }: { payments: Payment[] }) {
  const t = useTranslations("tracker");
  if (payments.length === 0) return null;
  return (
    <Section title={t("payment.title")} headingId="payments-heading" description={t("payment.lead")}>
      <RowList>
        {payments.map((p) => {
          const confirmed = p.confirmed_at !== null;
          return (
            <Row
              key={p.id}
              data-payment={confirmed ? "confirmed" : "recorded"}
              title={<Kes minor={p.amount_kes_minor} className="font-display text-xl font-bold" />}
              badges={[
                <Chip key="state" kind={confirmed ? "completed" : "current"}>
                  {confirmed ? t("payment.confirmed") : t("payment.recorded")}
                </Chip>,
              ]}
            >
              <DescriptionList dense figures className="mt-2">
                <Description label={t("payment.method")}>{t(`paymentMethod.${p.method}`)}</Description>
                {p.reference ? <Description label={t("payment.reference")}>{p.reference}</Description> : null}
                <Description label={t("payment.paidOn")}>
                  <Day day={p.paid_on} />
                </Description>
                <Description label={t("payment.recordedAt")}>
                  <Eat iso={p.recorded_at} />
                </Description>
                <Description label={t("payment.confirmedAt")}>
                  {p.confirmed_at ? (
                    <>
                      <Eat iso={p.confirmed_at} />
                      {p.confirmed_amount_kes_minor !== null ? (
                        <span className="block">
                          <Kes minor={p.confirmed_amount_kes_minor} />
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-ink-soft">{t("payment.notConfirmed")}</span>
                  )}
                </Description>
              </DescriptionList>
            </Row>
          );
        })}
      </RowList>
    </Section>
  );
}

/** The organisation's named contact person, channel and contact-by date (stage 3). */
export function ContactPerson({ detail }: { detail: Pick<Detail, "contact" | "my_party" | "org_name"> }) {
  const t = useTranslations("tracker");
  const contact = detail.contact;
  if (!contact) return null;
  return (
    <Section title={t("contact.title")} headingId="contact-heading">
      <DescriptionList>
        <Description label={t("contact.person")}>
          {contact.name ?? t("endorsements.platform")}
          {contact.role ? (
            <span className="ml-2 text-sm text-ink-soft">
              {ROLES.has(contact.role) ? t(`role.${contact.role as Endorsement["role"]}`) : contact.role}
            </span>
          ) : null}
        </Description>
        <Description label={t("contact.channel")}>{t(`channel.${contact.channel}`)}</Description>
        <Description label={t("contact.by")}>
          <Day day={contact.contact_by} />
        </Description>
      </DescriptionList>
    </Section>
  );
}
