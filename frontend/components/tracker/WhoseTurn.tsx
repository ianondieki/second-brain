import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";

import { ChipMark } from "./Chip";
import { formatDay } from "@/lib/format";

import { formatDate, myNextSteps, sideBanner, theirNextSteps, turnOf, type Detail, type SideBanner } from "./model";
import { DueText } from "./When";

/**
 * The "whose turn" banner on every tracker (docs/spec/07 item 2; docs/spec/06 6.9): "Awaiting: <party>" from the
 * API's `whose_turn`, the next step each party owes from `awaiting`, and the stage's countdown. The same for both
 * parties apart from the wording of "you". A side state is said here, on the stage where it occurred (never an extra
 * step): the open question, the hold with its reason and date, an expiry in words, the answer that resumed the stage.
 */
export function WhoseTurn({ detail }: { detail: Detail }) {
  const t = useTranslations("tracker");
  const steps = useTranslations("trackerActions");
  const locale = useLocale();
  const turn = turnOf(detail, detail.my_party);
  const other = detail.my_party === "developer" ? detail.org_name : detail.developer_name;
  const mine = myNextSteps(detail);
  const theirs = theirNextSteps(detail);

  const headline =
    turn.kind === "you"
      ? t("turn.you")
      : turn.kind === "other"
        ? t("turn.other", { name: other })
        : turn.kind === "both"
          ? t("turn.both", { name: other })
          : turn.kind === "none"
            ? t("turn.none")
            : detail.state === "CLOSED"
              ? t("turn.closed")
              : t("turn.ended");

  const yours = turn.kind === "you" || turn.kind === "both";
  const awaited = new Set(detail.whose_turn);
  const ended = turn.kind === "ended";
  const side = sideBanner(detail);
  const onHold = side?.kind === "hold";
  // While a question is open the countdown is its answer-by date, said in the question's own sentence; a hold's date
  // is in its sentence too. Past the answer-by date the overdue countdown shows instead.
  const countdown = detail.due && !ended && !onHold && (side?.kind !== "info" || detail.due.overdue);
  // The page's headline object (docs/platform/design/p20-design-system.md, tracker): a section without a frame of its
  // own (EngagementScreen draws the turn card around it and the actions). Saffron only for "Your turn"; the drawn
  // mark says current, completed, on hold or ended with the words otherwise. `data-callout` keeps the banner's tone.
  const tone = yours ? "info" : "neutral";
  const late = detail.due ? Math.abs(detail.due.business_days_left) : 0;
  // The countdown as a figure ("7 business days left") when it is a count; "due today" stays a sentence.
  const figure = countdown && detail.due && (detail.due.overdue ? late > 0 : detail.due.business_days_left > 0);
  return (
    <section
      aria-labelledby="whose-turn"
      data-whose-turn={turn.kind}
      data-callout={tone}
      className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8 sm:p-7"
    >
      <div className="min-w-0 flex-1">
        {yours ? (
          <p className="mb-3">
            <Badge tone="warm" solid icon={<ChipMark kind="current" />}>
              {t("yourTurn")}
            </Badge>
          </p>
        ) : null}
        {/* The headline, and the two parties beside it (the one whose turn it is ringed). */}
        {/* A long headline ("This engagement is closed.") keeps its line; the parties then wrap under it. */}
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <h2 id="whose-turn" className="flex min-w-0 items-start gap-2.5 text-xl text-ink sm:text-2xl">
            {yours ? null : (
              <ChipMark
                kind={turn.kind === "ended" ? (detail.state === "CLOSED" ? "completed" : "ended") : onHold ? "onHold" : "current"}
                className={cn(
                  "mt-1.5 size-5 sm:mt-2",
                  turn.kind === "ended" ? (detail.state === "CLOSED" ? "text-ok" : "text-ink-soft") : onHold ? "text-ink" : "text-accent",
                )}
              />
            )}
            <span className="min-w-0">{onHold ? t("turn.onHold") : headline}</span>
          </h2>
          <p className="flex shrink-0 items-center gap-1.5 pt-0.5" aria-label={t("parties")}>
            <Avatar name={detail.developer_name} kind="person" size="md" surface="field" active={!ended && awaited.has("developer")} labelled />
            <span aria-hidden="true" className="h-px w-3 bg-line sm:w-5" />
            <Avatar name={detail.org_name} kind="org" size="md" surface="field" active={!ended && awaited.has("org")} labelled />
          </p>
        </div>
        <div className="mt-4 flex flex-col gap-2.5 empty:hidden">
          {side ? <SideState side={side} detail={detail} /> : null}
          {turn.kind === "ended" && detail.end_reason && side?.kind !== "expired" ? (
            <p className="text-ink">{t("endedBecause", { reason: t(`endReason.${detail.end_reason}`) })}</p>
          ) : null}
          {/* The next step, said once: when both parties owe the same step, one sentence names them both. */}
          {turn.kind === "both" && mine.length === 1 && theirs.length === 1 && mine[0] === theirs[0] ? (
            <p className="text-lg font-semibold text-ink">{t("nextBoth", { name: other, step: steps(`command.${mine[0]}`) })}</p>
          ) : (
            <>
              {yours
                ? mine.map((command) => (
                    <p key={command} className="text-lg font-semibold text-ink">
                      {t("nextYou", { step: steps(`command.${command}`) })}
                    </p>
                  ))
                : null}
              {turn.kind === "other" || turn.kind === "both"
                ? theirs.map((command) => (
                    <p key={command} className={turn.kind === "other" ? "text-lg text-ink" : "text-ink-soft"}>
                      {t("nextThem", { name: other, step: steps(`command.${command}`) })}
                    </p>
                  ))
                : null}
            </>
          )}
          {side?.kind === "info" && detail.due && !detail.due.overdue ? (
            <p data-info-clock="" className="text-sm text-ink-soft">
              {t.rich(detail.my_party === "developer" ? "side.infoClockYou" : "side.infoClockThem", {
                name: detail.developer_name,
                date: formatDate(detail.due.due_on, locale),
                nowrap,
              })}
            </p>
          ) : null}
          {/* With a figure beside it the sentence is for screen readers (the figure is its picture); otherwise shown. */}
          {countdown && detail.due ? (
            <p className={figure ? "sr-only" : "text-sm"}>
              <DueText due={detail.due} className={detail.due.overdue ? "font-semibold text-error" : "text-ink-soft"} />
            </p>
          ) : null}
        </div>
      </div>
      {figure && detail.due ? <Countdown due={detail.due} /> : null}
    </section>
  );
}

/**
 * The stage's countdown as a figure (the display face, tabular): business days left, or overdue in the error colour
 * with its mark. A picture of the sentence beside it (aria-hidden): the sentence is what is read out.
 */
function Countdown({ due }: { due: Detail["due"] & object }) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  const count = Math.abs(due.business_days_left);
  const date = formatDate(due.due_on, locale);
  // One message, the figure tagged in it (<n>), so each language places its words around the number. A grid: the
  // figure beside its words on phones, above them from 640 px.
  const figure = (chunks: ReactNode) => (
    <span className="row-span-2 flex items-center gap-2 font-display text-3xl leading-none font-bold tabular-nums sm:row-span-1 sm:mb-1 sm:text-4xl">
      {due.overdue ? <ChipMark kind="overdue" className="size-6" /> : null}
      {chunks}
    </span>
  );
  return (
    <div
      aria-hidden="true"
      data-countdown={due.overdue ? "overdue" : "open"}
      className={cn(
        "grid shrink-0 grid-cols-[auto_1fr] items-center gap-x-4 border-t border-line pt-3 text-sm leading-snug font-semibold sm:w-40 sm:grid-cols-1 sm:items-start sm:border-t-0 sm:border-l sm:pt-0 sm:pl-6",
        due.overdue ? "text-error" : "text-ink",
      )}
    >
      {t.rich(due.overdue ? "deadline.overdue" : "deadline.left", { count, n: figure })}
      <span className="font-normal text-ink-soft">{t(due.overdue ? "deadline.was" : "deadline.due", { date })}</span>
    </div>
  );
}

const nowrap = (chunks: ReactNode) => <span className="whitespace-nowrap">{chunks}</span>;
/** A party's own words (a question, an answer, a reason), quoted as plain text on lines of their own. */
const quote = (chunks: ReactNode) => (
  <span data-note-text="" className="mt-1 block border-l-2 border-line pl-3 whitespace-pre-line text-ink [overflow-wrap:anywhere]">
    {chunks}
  </span>
);

/**
 * The side state's sentence in the banner. The texts are the parties' own, rendered as text (React escapes them;
 * nothing in them becomes a link or markup).
 */
function SideState({ side, detail }: { side: SideBanner; detail: Detail }) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  const nameOf = (party: Detail["my_party"]) => (party === "developer" ? detail.developer_name : detail.org_name);
  if (side.kind === "expired") {
    return side.reason && side.reason in EXPIRED ? (
      <p data-side="expired" className="text-ink">
        {t(`expired.${side.reason as keyof typeof EXPIRED}`)}
      </p>
    ) : null;
  }
  if (side.kind === "info") {
    return side.question ? (
      <p data-side="info" className="text-ink">
        {t.rich("side.info", { date: formatDay(locale, side.question.at), question: side.question.body, quote, nowrap })}
      </p>
    ) : null;
  }
  if (side.kind === "answered") {
    return (
      <p data-side="answered" className="text-ink">
        {t.rich("side.answered", { date: formatDay(locale, side.answer.at), answer: side.answer.body, quote, nowrap })}
      </p>
    );
  }
  const until = side.hold?.resume_at ?? detail.due?.due_on ?? null;
  const date = until ? formatDate(until, locale) : "";
  return (
    <>
      {side.hold ? (
        <p data-side="hold" className="text-ink">
          {side.hold.by === detail.my_party
            ? t.rich("side.holdYou", { date, reason: side.hold.body, quote, nowrap })
            : t.rich("side.hold", { name: nameOf(side.hold.by), date, reason: side.hold.body, quote, nowrap })}
        </p>
      ) : until ? (
        <p data-side="hold" className="text-ink">
          {t.rich("side.holdNoNote", { date, nowrap })}
        </p>
      ) : null}
      <p className="text-sm text-ink-soft">{t("side.holdClock")}</p>
    </>
  );
}

/** The four expiry reasons, each said as a whole sentence (tracker.expired.*). */
const EXPIRED = { NO_REVIEW: 1, NO_DECISION: 1, CONTACT_NOT_MADE: 1, NO_DEV_RESPONSE: 1 } as const;
