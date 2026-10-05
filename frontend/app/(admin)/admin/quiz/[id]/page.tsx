import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { isUuid } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { safeHttpsUrl } from "@/components/problem/problem";
import { Badge } from "@/components/ui/Badge";
import { BackLink } from "@/components/ui/BackLink";
import { textLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { EmptyState } from "@/components/ui/EmptyState";
import { CheckIcon, ClockIcon, ClosedIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { formatCalendarDate, formatMoment } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../../AdminShell";
import { QueueSummary } from "../../QueueSurface";
import { PageStepUp } from "../../research/PageStepUp";
import { staffContext } from "../../staff";
import { stepUpStrings } from "../../strings";
import { getQuizSet } from "../data";
import { QuestionActions } from "../QuestionActions";
import { ADMIN_QUIZ_PATH, averageScore, flagReason, isDayOver, nairobiDay, pulledBecause, type QuizAdminQuestion } from "../quiz";
import { SetDecision } from "../SetDecision";
import { topicLabel } from "@/app/(app)/dev/quiz/quiz";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminQuiz");
  return { title: t("set.pageTitle") };
}

const STATUS = {
  draft: { tone: "accent", Icon: ClockIcon },
  approved: { tone: "ok", Icon: CheckIcon },
  rejected: { tone: "neutral", Icon: ClosedIcon },
  dayOver: { tone: "warm", Icon: ClockIcon },
} as const;

/**
 * One quiz set under review (REQ-DEV-01; D-59): its five questions with the answer, why and source each, the flags
 * developers sent (by reason, with their notes; never who), the plays in aggregate (from three plays on), Pull or
 * Restore per question, and for a draft the decision, the screen's one primary action. Staff admins only.
 */
export default async function QuizSetPage({ params }: PageProps<"/admin/quiz/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const [t, locale] = await Promise.all([getTranslations("adminQuiz"), getLocale()]);
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current={role === "admin" ? "quiz" : undefined} wide>
      <div className="max-w-4xl">
        <BackLink href={ADMIN_QUIZ_PATH}>{t("set.back")}</BackLink>
        {children}
      </div>
    </AdminShell>
  );
  const empty = (sentence: string, action: string, href: string) =>
    shell(
      <>
        <PageHeader title={t("set.pageTitle")} focusable />
        <div className="mt-6">
          <EmptyState sentence={sentence} action={action} href={href} />
        </div>
      </>,
    );
  if (role !== "admin") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (!isUuid(id)) return empty(t("set.gone"), t("set.goneAction"), ADMIN_QUIZ_PATH);

  const loaded = await getQuizSet(id);
  if (loaded.kind === "forbidden") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (loaded.kind === "stepUp") {
    return shell(
      <>
        <PageHeader title={t("set.pageTitle")} focusable />
        <div className="mt-6">
          <ClientStrings strings={await stepUpStrings()}>
            <PageStepUp />
          </ClientStrings>
        </div>
      </>,
    );
  }
  const set = loaded.data;
  if (!set) return empty(t("set.gone"), t("set.goneAction"), ADMIN_QUIZ_PATH);

  const day = formatCalendarDate(locale, set.quiz_date);
  const dayOver = isDayOver(set, nairobiDay(new Date()));
  const status = dayOver ? "dayOver" : set.status;
  const { tone, Icon } = STATUS[status];
  const average = averageScore(locale, set.stats.average_score);
  const questions = [...set.questions].sort((a, b) => a.position - b.position);
  const strings = { ...(await clientStrings(["adminQuiz"])), ...(await stepUpStrings()) };

  return shell(
    <article aria-labelledby="set-title" className="flex flex-col gap-12">
      <PageHeader titleId="set-title" focusable title={t("set.title", { date: day })}>
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-soft">
          <Badge tone={tone} icon={<Icon />} data-set-status={status}>
            {t(`status.${status}`)}
          </Badge>
          <span>{t(`origin.${set.origin}`)}</span>
          {set.decided_at ? <span>{t("set.decided", { date: formatMoment(locale, set.decided_at) })}</span> : null}
        </p>
      </PageHeader>

      <Section title={t("set.statsHeading")} headingId="set-stats">
        <div className="rounded-panel border border-line bg-field px-4 py-4 sm:px-6">
          <QueueSummary
            figures={[
              { key: "attempts", label: t("set.attempts"), value: set.stats.attempts },
              {
                key: "average",
                label: t("set.average"),
                value: average ? (
                  t("set.averageValue", { value: average })
                ) : (
                  <span className="font-sans text-base font-semibold tracking-normal text-ink-soft">{t("set.notEnough")}</span>
                ),
              },
              { key: "flags", label: t("columns.flags"), value: set.flags },
            ]}
          />
        </div>
      </Section>

      <Section title={t("set.questionsHeading")} headingId="set-questions">
        <ClientStrings strings={strings}>
          <ol aria-labelledby="set-questions" className="flex flex-col divide-y divide-line rounded-panel border border-line bg-field">
            {questions.map((question, index) => (
              <li key={question.id} className="px-4 py-6 sm:px-6" data-admin-question={question.position} data-status={question.status}>
                <AdminQuestion question={question} right={set.stats.per_question_correct?.[index] ?? null} />
              </li>
            ))}
          </ol>
        </ClientStrings>
      </Section>

      {set.status === "draft" ? (
        // The decision is what the set needs from the admin now: raised, as on a research card.
        <Section
          title={t("decision.heading")}
          headingId="decision"
          description={t("decision.lead")}
          className="rounded-panel border border-line bg-field p-5 shadow-card sm:p-6"
        >
          <ClientStrings strings={strings}>
            <SetDecision setId={set.id} day={day} dayOver={dayOver} />
          </ClientStrings>
        </Section>
      ) : null}
    </article>,
  );
}

/** One question as staff review it: prompt, the four options with the answer marked, why, source, flags, actions. */
async function AdminQuestion({ question, right }: { question: QuizAdminQuestion; right: number | null }) {
  const [t, tq, locale] = await Promise.all([getTranslations("adminQuiz"), getTranslations("quiz"), getLocale()]);
  const href = safeHttpsUrl(question.source_url);
  const pulled = pulledBecause(question);
  const headingId = `question-${question.position}`;
  const reasons = Object.entries(question.flag_reasons).filter(([, count]) => count > 0);
  return (
    <article aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h3 id={headingId} className="text-base font-semibold text-ink">
          {t("question.heading", { number: question.position })}
        </h3>
        <Badge tone={question.status === "live" ? "ok" : "error"} icon={question.status === "live" ? <CheckIcon /> : <ClosedIcon />}>
          {t(`question.${question.status}`)}
        </Badge>
        <span className="text-sm text-ink-soft [overflow-wrap:anywhere]">{topicLabel(tq, question.topic)}</span>
      </div>
      <p className="text-lg font-semibold [overflow-wrap:anywhere] text-ink">{question.prompt}</p>
      <ul className="flex flex-col gap-2">
        {question.options.map((text, option) => (
          <li
            key={option}
            data-answer={option === question.answer ? "" : undefined}
            className={cn(
              "flex flex-col gap-2 rounded-control border px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between",
              option === question.answer ? "border-ok-line bg-ok-wash" : "border-line",
            )}
          >
            <span className="[overflow-wrap:anywhere] text-ink">{text}</span>
            {option === question.answer ? (
              <Badge tone="ok" icon={<CheckIcon />} className="shrink-0 self-start sm:self-auto">
                {t("question.answer")}
              </Badge>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="max-w-[68ch]">
        <p className="font-semibold text-ink">{t("question.why")}</p>
        <p className="mt-1 text-ink">{question.why}</p>
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="text-ink-soft">{t("question.source")}</span>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className={cn(textLinkClass, "[overflow-wrap:anywhere]")}>
            {question.source_title}
            <span className="sr-only"> {t("question.newTab")}</span>
          </a>
        ) : (
          <span className="text-ink">{question.source_title}</span>
        )}
      </p>
      {right !== null ? <p className="text-sm text-ink-soft tabular-nums">{t("set.rightCount", { count: right })}</p> : null}

      <div className="flex flex-col gap-2 border-t border-line pt-4 text-sm" data-flags={question.flags}>
        <p className="font-semibold text-ink">{question.flags > 0 ? t("question.flags", { count: question.flags }) : t("question.noFlags")}</p>
        {reasons.length > 0 ? (
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-ink-soft">
            {reasons.map(([code, count]) => (
              <span key={code}>{t("question.reasonCount", { name: t(`question.reason.${flagReason(code)}`), count })}</span>
            ))}
          </p>
        ) : null}
        {question.notes.length > 0 ? (
          <div>
            <p className="text-ink-soft">{t("question.notesHeading")}</p>
            <ul className="mt-1 flex flex-col gap-1.5">
              {question.notes.map((note, index) => (
                <li key={index} className="[overflow-wrap:anywhere] text-ink">
                  <span className="text-ink-soft">{formatMoment(locale, note.created_at)}</span>{" "}
                  {note.note}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {pulled ? (
          <p className="text-ink" data-pulled-reason="">
            {"byFlags" in pulled ? t("question.pulledByFlags") : t("question.pulledBecause", { value: pulled.reason })}
          </p>
        ) : null}
        {question.restored_at ? <p className="text-ink">{t("question.restored")}</p> : null}
      </div>
      <QuestionActions questionId={question.id} number={question.position} status={question.status} />
    </article>
  );
}
