import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, InfoIcon } from "@/components/ui/icons";

import { AdminShell } from "../../../AdminShell";
import { PageStepUp } from "../../../research/PageStepUp";
import { staffContext } from "../../../staff";
import { stepUpStrings } from "../../../strings";
import { CaseDecision } from "../../CaseDecision";
import { decidedLine } from "../../CaseRow";
import { getCase } from "../../data";
import {
  caseHref,
  caseKind,
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
 * alone), and the decision. A case that is in neither list reads as gone.
 */
export default async function CasePage({ params }: PageProps<"/admin/moderation/cases/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const t = await getTranslations("adminModeration");
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current="moderation">
      <p className="-mt-2 mb-4">
        <Link href={MODERATION_PATH} className={standaloneLinkClass}>
          {t("case.back")}
        </Link>
      </p>
      {children}
    </AdminShell>
  );
  const plain = (children: ReactNode) =>
    shell(
      <>
        <h1 tabIndex={-1} className="text-xl text-ink focus:outline-none lg:text-2xl">
          {t("case.pageTitle")}
        </h1>
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

  const locale = await getLocale();
  const kind = caseKind(item.subject_type);
  const seen = visibility(item);
  const result = outcome(item);
  const line = await decidedLine(item);
  const flagged = new Set(item.flagged_fields);
  const actionable = !result && item.actions.length > 0;

  return shell(
    <article aria-labelledby="case-title" className="flex flex-col gap-10">
      <header className="flex flex-col gap-2">
        <p className="text-sm font-semibold text-jacaranda">{t(`kind.${kind}`)}</p>
        <h1
          id="case-title"
          tabIndex={-1}
          className="text-xl [overflow-wrap:anywhere] text-ink focus:outline-none lg:text-2xl"
        >
          {caseTitle(item) ?? t(`untitled.${kind}`)}
        </h1>
        <ul className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          {/* Once decided, the outcome: "Public while checked" or "Hidden until decided" would no longer be true. */}
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
      </header>

      <section aria-labelledby="reasons" className="flex flex-col gap-3">
        <h2 id="reasons" className="text-lg text-ink">
          {t("case.reasonsHeading")}
        </h2>
        <ul className="flex flex-col gap-2" data-reasons="">
          {caseReasons(item.reasons).map((reason) => (
            <li key={reason} className="flex items-start gap-2 text-ink">
              {reasonTone(reason) === "flag" ? (
                <AlertIcon className="mt-0.5 size-5 shrink-0 text-error" />
              ) : (
                <InfoIcon className="mt-0.5 size-5 shrink-0 text-jacaranda" />
              )}
              <span>{t(`reason.${reason}`)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="text" className="flex flex-col gap-4">
        <div>
          <h2 id="text" className="text-lg text-ink">
            {t("case.textHeading")}
          </h2>
          <p className="mt-1 max-w-[60ch] text-ink-soft">{t("case.textLead")}</p>
        </div>
        <CaseText item={item} flagged={flagged} label={t("case.flagged")} empty={t("case.noText")} />
      </section>

      <section aria-labelledby="decision" className="flex flex-col gap-4 border-t border-line pt-6">
        <div>
          <h2 id="decision" className="text-lg text-ink">
            {t("case.decisionHeading")}
          </h2>
          {actionable ? (
            <p className="mt-1 max-w-[60ch] text-ink-soft">
              {seen === "public" ? t("case.leadPublic") : t("case.leadHidden")}
            </p>
          ) : null}
        </div>
        {/* Keyed, so it keeps its state (the status line) when a refresh changes what is around it. */}
        <ClientStrings key="decision" strings={await caseStrings()}>
          <CaseDecision
            caseId={item.id}
            versionId={item.subject_version_id}
            kind={kind === "problem" ? "problem" : kind === "proposal" ? "proposal" : "other"}
            actions={result ? [] : item.actions}
            blocked={item.blocked}
            decided={result && line ? { outcome: result, line } : null}
            nextHref={nextId ? caseHref(nextId) : null}
          />
        </ClientStrings>
      </section>
    </article>,
  );
}

/**
 * The subject's Tier-1 text as it reads now, field by field. A flagged field carries a margin rule, a mark and the
 * word "Flagged" beside its name, so the flag is never colour alone.
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
    <dl className="flex flex-col gap-5 rounded-panel border border-line bg-field px-3 py-4 sm:px-6 sm:py-5">
      {item.fields.map((field) => {
        const marked = flagged.has(field.name);
        return (
          <div
            key={field.name}
            data-field={field.name}
            data-flagged={marked ? "" : undefined}
            className={cn("border-l-[3px] pl-3 sm:pl-4", marked ? "border-error" : "border-transparent")}
          >
            <dt className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium text-ink-soft">
              <span>{t(`field.${fieldKey(field.name)}`)}</span>
              {marked ? (
                <span className="inline-flex items-center gap-1 font-semibold text-error">
                  <AlertIcon className="size-4 shrink-0" />
                  {label}
                </span>
              ) : null}
            </dt>
            <dd className="mt-1 max-w-[65ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">{field.text}</dd>
          </div>
        );
      })}
    </dl>
  );
}
