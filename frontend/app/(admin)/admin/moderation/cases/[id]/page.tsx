import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { cn } from "@/components/ui/cn";
import { AlertIcon, InfoIcon } from "@/components/ui/icons";
import { BackLink } from "@/components/ui/BackLink";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";

import { AdminShell } from "../../../AdminShell";
import { PageStepUp } from "../../../research/PageStepUp";
import { staffContext } from "../../../staff";
import { stepUpStrings } from "../../../strings";
import { CaseDecision } from "../../CaseDecision";
import { decidedLine } from "../../CaseRow";
import { getCase } from "../../data";
import { MessageCase } from "../../MessageCase";
import {
  caseHref,
  caseKind,
  caseKindLabel,
  isBriefCase,
  caseReasons,
  caseTitle,
  fieldKey,
  MODERATION_PATH,
  outcome,
  reasonTone,
  visibility,
  VISIBILITY_CHIP,
  type Case,
} from "../../moderation";
import { caseStrings } from "../../strings";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminModeration");
  return { title: t("case.pageTitle") };
}

const ROLES = new Set(["admin", "moderator"]);

/**
 * One moderation case (REQ-MOD-01; docs/spec/06 6.12; M2 walkthrough step 6): why it was filed, the subject's public
 * summary (Tier 1 only) field by field with the flagged fields marked by a margin rule, a mark and a word (never colour
 * alone), and the decision. A case that does not exist reads as gone (it is read by its id, wherever it falls in the
 * queue).
 */
export default async function CasePage({ params }: PageProps<"/admin/moderation/cases/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const t = await getTranslations("adminModeration");
  const shell = (children: ReactNode, wide = false) => (
    <AdminShell role={role} current="moderation" wide={wide}>
      <BackLink href={MODERATION_PATH}>{t("case.back")}</BackLink>
      {children}
    </AdminShell>
  );
  const plain = (children: ReactNode) =>
    shell(
      <>
        <PageHeader title={t("case.pageTitle")} focusable />
        <div className="mt-6">{children}</div>
      </>,
    );
  const notAllowed = () =>
    plain(<EmptyState sentence={t("notAllowed")} action={t("notAllowedAction")} href="/admin" />);
  const gone = () =>
    plain(<EmptyState sentence={t("case.gone")} action={t("case.goneAction")} href={MODERATION_PATH} />);
  if (!ROLES.has(role)) return notAllowed();
  if (!isUuid(id)) return gone();

  const loaded = await getCase(id);
  if (loaded.kind === "forbidden") return notAllowed();
  if (loaded.kind === "stepUp") {
    return plain(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }
  const { item, nextId } = loaded.data;
  if (!item) return gone();
  // A party's report of an engagement message: its own page (the message quoted, Dismiss or Uphold; REQ-ENG-11).
  if (caseKind(item.subject_type) === "message") return shell(<MessageCase item={item} nextId={nextId} />, true);

  const locale = await getLocale();
  const kind = caseKind(item.subject_type);
  const label = caseKindLabel(item);
  const kindText = label.key === "briefBy" ? t("kind.briefBy", { org: label.org }) : t(`kind.${label.key}`);
  const seen = visibility(item);
  const result = outcome(item);
  const line = await decidedLine(item);
  const flagged = new Set(item.flagged_fields);
  const actionable = !result && item.actions.length > 0;

  // Once the subject is gone there is no text to review; once decided, the text is no longer "under review".
  const subjectGone = seen === "gone";
  return shell(
    <article aria-labelledby="case-title" className="flex max-w-5xl flex-col gap-10 lg:gap-12">
      <PageHeader titleId="case-title" focusable title={caseTitle(item) ?? t(`untitled.${kind}`)}>
        {/* What the case is about, then whether the subject can be seen now (or, once decided, the outcome: "Public
            while checked" or "Hidden until decided" would no longer be true), as the meta line. */}
        <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          <li data-header-tag="kind">
            <Badge tone="neutral">{kindText}</Badge>
          </li>
          {result ? (
            <li data-header-tag="outcome">
              <Chip kind={result === "approved" ? "completed" : "ended"}>{t(`outcome.${result}`)}</Chip>
            </li>
          ) : seen ? (
            <li data-header-tag="visibility">
              <Chip kind={VISIBILITY_CHIP[seen]}>{t(`visibility.${seen}`)}</Chip>
            </li>
          ) : null}
          <li>{t("filed", { date: formatMoment(locale, item.created_at) })}</li>
          <li>{t(`source.${item.source}`)}</li>
        </ul>
      </PageHeader>

      {/* From 1024 px the text is read on the left while why it is here and the decision stay beside it (the
          decision sticky, so a long text never hides the buttons); on a phone the three follow in reading order. */}
      <div
        className={cn(
          "grid grid-cols-1 items-start gap-12",
          subjectGone ? "max-w-xl" : "lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-x-10 lg:gap-y-8",
        )}
      >
        <Section title={t("case.reasonsHeading")} headingId="reasons" className={subjectGone ? undefined : "lg:col-start-2 lg:row-start-1"}>
          <ul className="flex flex-col gap-2" data-reasons="">
            {caseReasons(item.reasons).map((reason) => (
              <li key={reason} className="flex items-start gap-2 text-ink">
                {reasonTone(reason) === "flag" ? (
                  <AlertIcon className="mt-0.5 size-5 shrink-0 text-error" />
                ) : (
                  <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
                )}
                <span>{t(`reason.${reason}`)}</span>
              </li>
            ))}
          </ul>
        </Section>

        {subjectGone ? null : (
          <Section
            title={result ? t("case.textHeadingDecided") : t("case.textHeading")}
            headingId="text"
            description={result ? t("case.textLeadDecided") : t("case.textLead")}
            data-case-text=""
            className="lg:col-start-1 lg:row-span-2 lg:row-start-1"
          >
            <div className="rounded-panel border border-line bg-field p-5 sm:p-6">
              <CaseText item={item} flagged={flagged} label={t("case.flagged")} empty={t("case.noText")} />
            </div>
          </Section>
        )}

        <Section
          title={t("case.decisionHeading")}
          headingId="decision"
          className={cn(
            "decision-panel rounded-panel border bg-field p-5",
            !subjectGone && "lg:sticky lg:top-24 lg:col-start-2 lg:row-start-2",
          )}
        >
          {/* Keyed, so it keeps its state (the status line) when a refresh changes what is around it. */}
          <ClientStrings key="decision" strings={await caseStrings()}>
            <CaseDecision
              caseId={item.id}
              versionId={item.subject_version_id}
              kind={isBriefCase(item) ? "brief" : kind === "problem" ? "problem" : kind === "proposal" ? "proposal" : "other"}
              actions={result ? [] : item.actions}
              blocked={item.blocked}
              decided={result && line ? { outcome: result, line } : null}
              nextHref={nextId ? caseHref(nextId) : null}
              lead={
                actionable
                  ? seen === "briefHidden"
                    ? t("case.leadBrief")
                    : seen === "public"
                      ? t("case.leadPublic")
                      : t("case.leadHidden")
                  : null
              }
            />
          </ClientStrings>
        </Section>
      </div>
    </article>,
    true,
  );
}

/**
 * The subject's Tier-1 text as it reads now, field by field. A flagged field sits in the error notice's frame (1 px
 * error border, error wash) and carries a mark and the word "Flagged" beside its name, so the flag is never colour
 * alone; the other fields keep the same inset, so every field's text starts on one line.
 */
async function CaseText({
  item,
  flagged,
  label,
  empty,
}: {
  item: Case;
  flagged: ReadonlySet<string>;
  label: string;
  empty: string;
}) {
  const t = await getTranslations("adminModeration");
  if (item.fields.length === 0) return <p className="text-ink">{empty}</p>;
  return (
    <dl className={cn("flex flex-col", flagged.size > 0 ? "gap-3" : "gap-5")}>
      {item.fields.map((field) => {
        const marked = flagged.has(field.name);
        return (
          <div
            key={field.name}
            data-field={field.name}
            data-flagged={marked ? "" : undefined}
            className={cn(
              // Inset only when a field is flagged, so every field's text starts on the same line as the flagged one's.
              flagged.size > 0 && "rounded-control border px-4 py-3",
              marked ? "border-error-line bg-error-wash" : "border-transparent",
            )}
          >
            <dt className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium text-ink-soft">
              <span>{t(`field.${fieldKey(field.name)}`)}</span>
              {marked ? (
                <Badge tone="error" icon={<AlertIcon />}>
                  {label}
                </Badge>
              ) : null}
            </dt>
            <dd className="mt-1 max-w-[65ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">{field.text}</dd>
          </div>
        );
      })}
    </dl>
  );
}
