import { useLocale, useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Section } from "@/components/ui/Section";

import { Chip } from "./Chip";
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
export function Kes({ minor }: { minor: number }) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  return <span className="tabular-nums">{t("kes", { amount: kesAmount(minor, locale) })}</span>;
}

/** The latest agreement version in full; earlier versions folded away. */
export function Agreements({ detail }: { detail: Pick<Detail, "agreements" | "endorsements"> }) {
  const t = useTranslations("tracker");
  if (detail.agreements.length === 0) return null;
  const sorted = [...detail.agreements].sort((a, b) => b.version - a.version);
  const [latest, ...earlier] = sorted;
  return (
    <Section title={t("agreement.title")} headingId="agreement-heading">
      <AgreementVersion agreement={latest} endorsements={detail.endorsements} />
      {earlier.length > 0 ? (
        <details className="mt-4 border-t border-line pt-3">
          <summary className="flex min-h-11 cursor-pointer items-center font-semibold text-jacaranda">
            {t("agreement.earlier", { count: earlier.length })}
          </summary>
          {earlier.map((agreement) => (
            <AgreementVersion key={agreement.id} agreement={agreement} endorsements={[]} className="mt-3" />
          ))}
        </details>
      ) : null}
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
    <article data-agreement={agreement.status} className={cn("border-t border-line pt-4", className)}>
      <h3 className="flex flex-wrap items-center gap-x-4 gap-y-1 font-semibold text-ink">
        {t("agreement.version", { version: agreement.version })}
        <Chip kind={status}>{t(`agreement.status.${agreement.status}`)}</Chip>
      </h3>
      <p className="mt-1 text-sm text-ink-soft">
        {t(`agreement.draftedBy.${agreement.drafted_by}`, { when: eat(agreement.created_at) })}
      </p>
      <DescriptionList className="mt-3">
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
          <h4 className="mt-5 font-semibold text-ink">{t("milestone.title")}</h4>
          <ol className="mt-2 flex flex-col">
            {[...agreement.milestones]
              .sort((a, b) => a.seq - b.seq)
              .map((milestone) => (
                <li key={milestone.id} className="border-t border-line py-3">
                  <MilestoneRow
                    milestone={milestone}
                    endorsements={endorsements.filter((e) => e.milestone_id === milestone.id)}
                    live={agreement.status === "signed"}
                  />
                </li>
              ))}
          </ol>
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
        <Kes minor={milestone.amount_kes_minor} />
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

/** Who signed which document, when and with which second factor, with the fingerprint signed. */
export function Signatures({ signatures }: { signatures: Signature[] }) {
  const t = useTranslations("tracker");
  if (signatures.length === 0) return null;
  return (
    <Section title={t("signature.title")} headingId="signatures-heading">
      <ul className="flex flex-col">
        {signatures.map((s) => (
          <li key={s.id} data-signature={s.document_kind} className="border-t border-line py-3">
            <p className="font-semibold text-ink">{t(`document.${s.document_kind}`)}</p>
            <p className="mt-0.5 text-sm text-ink">
              {t("signature.by", {
                name: s.signer_name ?? t("endorsements.platform"),
                party: t(`party.${s.party}`),
                method: t(`method.${s.step_up_method}`),
              })}
            </p>
            <p className="mt-0.5 flex flex-wrap gap-x-4 text-sm text-ink-soft">
              <Eat iso={s.signed_at} />
              <span className="tabular-nums">{t("fingerprint", { hash: shortHash(s.document_sha256) })}</span>
            </p>
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
      <ul className="flex flex-col">
        {payments.map((p) => {
          const confirmed = p.confirmed_at !== null;
          return (
            <li key={p.id} data-payment={confirmed ? "confirmed" : "recorded"} className="border-t border-line py-3">
              <p className="flex flex-wrap items-baseline justify-between gap-x-4">
                <span className="font-semibold text-ink">
                  <Kes minor={p.amount_kes_minor} />
                </span>
                <Chip kind={confirmed ? "completed" : "current"}>
                  {confirmed ? t("payment.confirmed") : t("payment.recorded")}
                </Chip>
              </p>
              <DescriptionList dense className="mt-2">
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
            </li>
          );
        })}
      </ul>
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
