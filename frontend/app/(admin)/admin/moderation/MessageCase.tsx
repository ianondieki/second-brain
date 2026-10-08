import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { AlertIcon } from "@/components/ui/status-icons";

import { decidedLine } from "./CaseRow";
import { MessageDecision } from "./MessageDecision";
import { caseHref, messageReasons, outcomeChip, outcomeKey, type Case } from "./moderation";
import { caseStrings } from "./strings";

/**
 * A party's report of one engagement message (REQ-ENG-11; D-57 (4)): the reasons the reporter chose, the one message
 * the report shares (its sender's side, its time and its text, quoted as plain text; never the rest of the thread),
 * and the decision: Dismiss (the message breaks no rule) or Uphold, each with an optional note. A report the moderator
 * filed, or one about an engagement they are a party of, says so instead of offering the decision.
 */
export async function MessageCase({ item, nextId }: { item: Case; nextId: string | null }) {
  const t = await getTranslations("adminModeration");
  const locale = await getLocale();
  const result = outcomeKey(item);
  const line = await decidedLine(item);
  const message = item.message ?? null;
  return (
    <article aria-labelledby="case-title" className="flex max-w-5xl flex-col gap-10 lg:gap-12">
      <PageHeader titleId="case-title" focusable title={t("untitled.message")}>
        <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
          <li data-header-tag="kind">
            <Badge tone="neutral">{t("kind.message")}</Badge>
          </li>
          {result ? (
            <li data-header-tag="outcome">
              <Chip kind={outcomeChip(result)}>{t(`outcome.${result}`)}</Chip>
            </li>
          ) : null}
          <li>{t("filed", { date: formatMoment(locale, item.created_at) })}</li>
          <li>{t(`source.${item.source}`)}</li>
        </ul>
      </PageHeader>

      <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-x-10 lg:gap-y-8">
        <Section title={t("case.reasonsHeading")} headingId="reasons" className="lg:col-start-2 lg:row-start-1">
          <ul className="flex flex-col gap-2" data-reasons="">
            {messageReasons(item.reasons).map((reason) => (
              <li key={reason} className="flex items-start gap-2 text-ink">
                <AlertIcon className="mt-0.5 size-5 shrink-0 text-error" />
                <span>{t(`message.reason.${reason}`)}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section
          title={t("message.heading")}
          headingId="text"
          description={t("message.lead")}
          data-case-message=""
          className="lg:col-start-1 lg:row-span-2 lg:row-start-1"
        >
          {message ? (
            <figure className="rounded-panel border border-line bg-field p-5 sm:p-6">
              <figcaption className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
                <span className="font-semibold text-ink" data-sender={message.sender_party}>
                  {message.sender_party === "developer" ? t("message.fromDeveloper") : t("message.fromOrg")}
                </span>
                <time dateTime={message.created_at} className="text-ink-soft tabular-nums">
                  {t("message.sentAt", { date: formatMoment(locale, message.created_at) })}
                </time>
              </figcaption>
              {/* The text as the party typed it: plain text, its line breaks kept, never a link. */}
              <blockquote className="mt-4 max-w-[65ch] border-l-2 border-line pl-4 whitespace-pre-wrap [overflow-wrap:anywhere] text-ink" data-message-body="">
                {message.body}
              </blockquote>
              <p className="mt-4 text-xs text-ink-soft">{t("message.engagement", { id: message.engagement_id })}</p>
            </figure>
          ) : (
            <p className="text-ink">{t("case.noText")}</p>
          )}
        </Section>

        <Section
          title={t("case.decisionHeading")}
          headingId="decision"
          className="decision-panel rounded-panel border bg-field p-5 lg:sticky lg:top-24 lg:col-start-2 lg:row-start-2"
        >
          <ClientStrings key="decision" strings={await caseStrings()}>
            <MessageDecision
              caseId={item.id}
              actions={result ? [] : item.actions}
              blocked={item.blocked}
              decided={result && line ? { outcome: result, line } : null}
              nextHref={nextId ? caseHref(nextId) : null}
            />
          </ClientStrings>
        </Section>
      </div>
    </article>
  );
}
