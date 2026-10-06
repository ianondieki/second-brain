import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { topicLabel } from "@/app/(app)/dev/quiz/quiz";
import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { formatConfidence, safeHttpsUrl } from "@/components/problem/problem";
import { Badge } from "@/components/ui/Badge";
import { BackLink } from "@/components/ui/BackLink";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { CheckIcon, ClockIcon, ClosedIcon, InfoIcon, PencilIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { formatCalendarDate, formatMoment } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../../../AdminShell";
import { staffContext } from "../../../staff";
import { getTrendCard } from "../../data";
import { PageStepUp } from "../../PageStepUp";
import { RESEARCH_PATH } from "../../research";
import { TrendDecision } from "../TrendDecision";
import { seededTrend } from "../trends";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminResearch");
  return { title: t("trends.review.pageTitle") };
}

const STATUS = {
  candidate: { tone: "accent", Icon: ClockIcon },
  published: { tone: "ok", Icon: CheckIcon },
  rejected: { tone: "neutral", Icon: ClosedIcon },
} as const;

/**
 * One trend card (REQ-DEV-02; D-60; P22 card B default (5)): the card as developers would read it, how it was drafted,
 * its topic, confidence and the organisations it names, every source with its quote as published and the phrase the
 * card rests on, and for a candidate the decision (Publish, the screen's one primary action, or Reject; both confirmed,
 * behind the step-up). Staff admins only.
 */
export default async function TrendReviewPage({ params }: PageProps<"/admin/research/trends/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const [t, tq, locale] = await Promise.all([getTranslations("adminResearch"), getTranslations("quiz"), getLocale()]);
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current="research" wide>
      <div className="max-w-3xl">
        <BackLink href={RESEARCH_PATH}>{t("trends.review.back")}</BackLink>
        {children}
      </div>
    </AdminShell>
  );
  const empty = (sentence: string, action: string, href: string) =>
    shell(
      <>
        <PageHeader title={t("trends.review.pageTitle")} focusable />
        <div className="mt-6">
          <EmptyState sentence={sentence} action={action} href={href} />
        </div>
      </>,
    );
  if (role !== "admin") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (!isUuid(id)) return empty(t("trends.review.gone"), t("trends.review.goneAction"), RESEARCH_PATH);

  const loaded = await getTrendCard(id);
  if (loaded.kind === "forbidden") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  const strings = await clientStrings(["adminResearch"]);
  if (loaded.kind === "stepUp") {
    return shell(
      <>
        <PageHeader title={t("trends.review.pageTitle")} focusable />
        <div className="mt-6">
          <ClientStrings strings={strings}>
            <PageStepUp />
          </ClientStrings>
        </div>
      </>,
    );
  }
  const card = loaded.data;
  if (!card) return empty(t("trends.review.gone"), t("trends.review.goneAction"), RESEARCH_PATH);

  const seeded = seededTrend(card);
  const { tone, Icon } = STATUS[card.status];
  const confidence = formatConfidence(locale, card.confidence);
  const sources = [...card.sources].sort((a, b) => a.position - b.position);

  return shell(
    <article aria-labelledby="trend-title" className="flex flex-col gap-12">
      <PageHeader titleId="trend-title" focusable title={card.title}>
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <Badge tone={tone} icon={<Icon />} data-trend-status={card.status}>
            {t(`trends.status.${card.status}`)}
          </Badge>
          <Badge tone="neutral" icon={seeded ? <InfoIcon /> : <PencilIcon />}>
            {seeded ? t("trends.seeded") : t("trends.aiDrafted")}
          </Badge>
        </p>
        <p className="mt-4 max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink">{card.summary}</p>
        <DescriptionList className="mt-6">
          <Description label={t("trends.review.topic")}>{topicLabel(tq, card.topic_slug)}</Description>
          {confidence ? <Description label={t("trends.review.confidence")}>{confidence}</Description> : null}
          <Description label={t("trends.review.drafted")}>{formatMoment(locale, card.created_at)}</Description>
          {card.named_orgs.length > 0 ? (
            <Description label={t("trends.review.namedOrgs")}>
              <ul className="flex flex-col gap-1">
                {card.named_orgs.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </Description>
          ) : null}
        </DescriptionList>
        {card.decided_at && card.status !== "candidate" ? (
          <p className="mt-4 text-sm text-ink-soft">{t("trends.review.decided", { date: formatMoment(locale, card.decided_at) })}</p>
        ) : null}
      </PageHeader>

      <Section title={t("trends.review.sourcesHeading")} headingId="trend-sources" description={t("trends.review.sourcesLead")}>
        <ol aria-labelledby="trend-sources" className="flex flex-col rounded-panel border border-line bg-field px-4 sm:px-6">
          {sources.map((source) => {
            const href = safeHttpsUrl(source.url);
            return (
              <li key={source.position} data-trend-source="" className="flex min-w-0 flex-col gap-3 border-t border-line py-5 first:border-t-0">
                <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-semibold [overflow-wrap:anywhere] text-ink">{source.publisher}</span>
                  <span className="text-sm text-ink-soft">{formatCalendarDate(locale, source.published_date)}</span>
                </p>
                <blockquote cite={href ?? undefined} className="max-w-[62ch] border-l-2 border-line pl-4 [overflow-wrap:anywhere] text-ink">
                  <p>{source.quote}</p>
                </blockquote>
                <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">{t("trends.review.support", { value: source.support })}</p>
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="-my-2.5 inline-flex min-h-11 max-w-full items-center self-start font-semibold [overflow-wrap:anywhere] text-accent underline decoration-1 hover:decoration-2"
                  >
                    {source.url}
                    <span className="sr-only"> {t("trends.review.newTab")}</span>
                  </a>
                ) : null}
              </li>
            );
          })}
        </ol>
      </Section>

      {card.status === "candidate" ? (
        <Section
          title={t("trends.review.decisionHeading")}
          headingId="decision"
          description={t("trends.review.decisionLead")}
          className="rounded-panel border border-line bg-field p-5 shadow-card sm:p-6"
        >
          <ClientStrings strings={strings}>
            <TrendDecision cardId={card.id} />
          </ClientStrings>
        </Section>
      ) : null}
    </article>,
  );
}
