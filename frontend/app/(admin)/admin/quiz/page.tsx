import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { Badge } from "@/components/ui/Badge";
import { DataCell, DataRow, DataTable, dataLinkClass } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { CheckIcon, ClockIcon, ClosedIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { formatCalendarDate } from "@/lib/format";

import { AdminShell } from "../AdminShell";
import { QueueSurface } from "../QueueSurface";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { getQuizSets } from "./data";
import { ADMIN_QUIZ_PATH, queue, setHref, type QuizSetSummary } from "./quiz";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminQuiz");
  return { title: t("pageTitle") };
}

/**
 * Quiz (REQ-DEV-01; D-59): the sets waiting for a staff admin's review (oldest day first, so today's comes before
 * tomorrow's), then the decided ones with their day, flags and pulled questions. Staff admins only, as the API; a
 * moderator is told it is not theirs; a stale second factor asks for a fresh code first.
 */
export default async function QuizQueuePage() {
  const { role } = await staffContext();
  const t = await getTranslations("adminQuiz");
  const header = <PageHeader title={t("title")} lead={t("lead")} focusable />;
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current={role === "admin" ? "quiz" : undefined} wide>
      <div className="flex max-w-5xl flex-col gap-12">
        {header}
        {children}
      </div>
    </AdminShell>
  );
  const refused = () => shell(<EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href="/admin" />);
  if (role !== "admin") return refused();

  const loaded = await getQuizSets();
  if (loaded.kind === "forbidden") return refused();
  if (loaded.kind === "stepUp") {
    return shell(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }

  const { waiting, decided } = queue(loaded.data);
  const columns = [t("columns.day"), t("columns.status"), t("columns.origin"), t("columns.flags"), t("columns.pulled")];

  return shell(
    <>
      <Section title={t("queue.heading")} headingId="quiz-waiting">
        {waiting.length > 0 ? (
          <QueueSurface>
            <DataTable aria-labelledby="quiz-waiting" columns={columns}>
              {waiting.map((set) => (
                <SetRow key={set.id} set={set} />
              ))}
            </DataTable>
          </QueueSurface>
        ) : (
          <EmptyState rule={false} sentence={t("queue.empty")} action={t("queue.emptyAction")} href={ADMIN_QUIZ_PATH} />
        )}
      </Section>

      {decided.length > 0 ? (
        <Section title={t("queue.decidedHeading")} headingId="quiz-decided">
          <QueueSurface raised={false}>
            <DataTable aria-label={t("queue.decidedLabel")} columns={columns}>
              {decided.map((set) => (
                <SetRow key={set.id} set={set} />
              ))}
            </DataTable>
          </QueueSurface>
        </Section>
      ) : null}
    </>,
  );
}

const STATUS = {
  draft: { tone: "accent", Icon: ClockIcon },
  approved: { tone: "ok", Icon: CheckIcon },
  rejected: { tone: "neutral", Icon: ClosedIcon },
} as const;

/** One set, a row of the queue: its day (the way in), its status (icon and words), who drafted it, flags, pulled. */
async function SetRow({ set }: { set: QuizSetSummary }) {
  const [t, locale] = await Promise.all([getTranslations("adminQuiz"), getLocale()]);
  const { tone, Icon } = STATUS[set.status];
  return (
    <DataRow data-quiz-set={set.id} data-status={set.status}>
      <DataCell head label={t("columns.day")} className="sm:w-[34%]">
        <Link href={setHref(set.id)} className={dataLinkClass}>
          {t("openSet", { date: formatCalendarDate(locale, set.quiz_date) })}
        </Link>
      </DataCell>
      <DataCell label={t("columns.status")} nowrap>
        <Badge tone={tone} icon={<Icon />}>
          {t(`status.${set.status}`)}
        </Badge>
      </DataCell>
      <DataCell label={t("columns.origin")}>{t(`origin.${set.origin}`)}</DataCell>
      <DataCell label={t("columns.flags")} figure nowrap>
        {set.flags}
      </DataCell>
      <DataCell label={t("columns.pulled")} figure nowrap>
        {set.pulled}
      </DataCell>
    </DataRow>
  );
}
