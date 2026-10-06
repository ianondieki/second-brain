import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { cn } from "@/components/ui/cn";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { formatCalendarDate, formatShortDate } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { quizBoard, quizCard } from "../data";
import { boardLine, QUIZ_PATH } from "../quiz";
import { OptIn } from "./OptIn";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("quiz");
  return { title: t("board.pageTitle") };
}

/**
 * Developer › Today's five › This week (REQ-DEV-01; D-59): the caller's own line first (points, and the rank once
 * they are on the board), the opt-in switch with who sees what, then the week's top 20 by handle. Opt-in only, by
 * handle, reset every Monday; organisations never see it. Developers only.
 */
export default async function BoardPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [t, locale, board, today] = await Promise.all([getTranslations("quiz"), getLocale(), quizBoard(), quizCard()]);
  const line = boardLine(board.me);
  // One way to play, said once: under the caller's line when they have no points yet, else on the empty list; a day
  // without a set to play (or a read that failed) points the empty list at Home instead.
  const canPlay = today?.kind === "set" && !today.today.attempt;
  const playOnLine = canPlay && line.key === "notPlayed";
  const emptyAction =
    canPlay && !playOnLine
      ? { label: t("board.emptyAction"), href: QUIZ_PATH }
      : { label: t("board.home"), href: "/dev" };
  const dates = t("board.dates", {
    start: formatShortDate(locale, board.week_start),
    end: formatCalendarDate(locale, board.week_end),
  });

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-10">
        <PageHeader back={{ href: QUIZ_PATH, label: t("board.back") }} title={t("board.title")} lead={t("board.lead")}>
          <p className="mt-3 font-display text-lg font-[620] text-ink tabular-nums" data-board-dates="">
            {dates}
          </p>
        </PageHeader>

        {/* The caller's own line: what this page is for them, raised. */}
        <section aria-label={t("board.you")} className="flex flex-col gap-4 rounded-panel border border-line bg-field p-5 shadow-card sm:p-6" data-board-me="">
          <p className="text-lg font-semibold text-ink tabular-nums" data-board-line={line.key}>
            {line.key === "ranked"
              ? t("board.me.ranked", { points: line.points, rank: line.rank })
              : line.key === "join"
                ? t("board.me.join", { points: line.points })
                : t("board.me.notPlayed")}
          </p>
          {playOnLine ? (
            <StandaloneLink href={QUIZ_PATH} className="-mt-2 self-start">
              {t("board.play")}
            </StandaloneLink>
          ) : null}
          <div className="border-t border-line pt-4">
            <ClientStrings strings={await clientStrings(["quizPlay"])}>
              <OptIn initial={board.me.opted_in} />
            </ClientStrings>
          </div>
        </section>

        <Section title={t("board.listHeading")} headingId="board-list">
          {board.rows.length === 0 ? (
            <EmptyState rule={false} sentence={t("board.empty")} action={emptyAction.label} href={emptyAction.href} />
          ) : (
            <ol aria-labelledby="board-list" className="flex flex-col divide-y divide-line rounded-panel border border-line bg-field">
              {board.rows.map((row) => (
                <li
                  key={`${row.rank}-${row.handle}`}
                  data-board-row={row.handle}
                  data-you={row.you ? "" : undefined}
                  className={cn("flex min-h-14 items-center gap-4 px-4 py-3 sm:px-6", row.you && "bg-accent-wash")}
                >
                  <span className="sr-only">{t("board.rank", { rank: row.rank })}</span>
                  <span aria-hidden="true" className="w-8 shrink-0 font-display text-xl font-[680] text-ink tabular-nums">
                    {row.rank}
                  </span>
                  <span className="min-w-0 flex-1 font-semibold [overflow-wrap:anywhere] text-ink">
                    {row.handle}
                    {row.you ? <span className="ml-2 text-sm font-semibold text-accent">{t("board.you")}</span> : null}
                  </span>
                  <span className="shrink-0 text-ink-soft tabular-nums">{t("board.points", { points: row.points })}</span>
                </li>
              ))}
            </ol>
          )}
        </Section>
      </div>
    </SignedInShell>
  );
}
