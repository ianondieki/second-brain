import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Callout } from "@/components/ui/Callout";
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
  // A Callout with a title (docs/platform/design/p16-design-system.md, Notices): the accent tone when it is the
  // viewer's turn, neutral otherwise; the drawn mark says current, completed or ended with the words.
  return (
    <Callout
      as="section"
      aria-labelledby="whose-turn"
      data-whose-turn={turn.kind}
      tone={yours ? "info" : "neutral"}
      title={onHold ? t("turn.onHold") : headline}
      titleId="whose-turn"
      titleSize="lg"
      icon={
        <ChipMark
          kind={turn.kind === "ended" ? (detail.state === "CLOSED" ? "completed" : "ended") : onHold ? "onHold" : "current"}
          className={cn(
            "mt-1 size-5",
            turn.kind === "ended" ? (detail.state === "CLOSED" ? "text-ok" : "text-ink-soft") : onHold ? "text-ink" : "text-accent",
          )}
        />
      }
    >
      <p className="flex items-center gap-2 py-0.5" aria-label={t("parties")}>
        <Avatar name={detail.developer_name} kind="person" size="md" surface="field" active={!ended && awaited.has("developer")} labelled />
        <Avatar name={detail.org_name} kind="org" size="md" surface="field" active={!ended && awaited.has("org")} labelled />
      </p>
      {side ? <SideState side={side} detail={detail} /> : null}
      {turn.kind === "ended" && detail.end_reason && side?.kind !== "expired" ? (
        <p className="text-ink">{t("endedBecause", { reason: t(`endReason.${detail.end_reason}`) })}</p>
      ) : null}
      {/* The next step, said once: when both parties owe the same step, one sentence names them both. */}
      {turn.kind === "both" && mine.length === 1 && theirs.length === 1 && mine[0] === theirs[0] ? (
        <p className="text-ink">{t("nextBoth", { name: other, step: steps(`command.${mine[0]}`) })}</p>
      ) : (
        <>
          {yours
            ? mine.map((command) => (
                <p key={command} className="text-ink">
                  {t("nextYou", { step: steps(`command.${command}`) })}
                </p>
              ))
            : null}
          {turn.kind === "other" || turn.kind === "both"
            ? theirs.map((command) => (
                <p key={command} className="text-ink-soft">
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
      {countdown && detail.due ? (
        <p className="text-sm">
          <DueText due={detail.due} className={detail.due.overdue ? "font-semibold text-error" : "text-ink-soft"} />
        </p>
      ) : null}
    </Callout>
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
