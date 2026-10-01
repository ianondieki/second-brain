import { useTranslations } from "next-intl";

import { Avatar } from "@/components/ui/Avatar";
import { Callout } from "@/components/ui/Callout";
import { cn } from "@/components/ui/cn";

import { ChipMark } from "./Chip";
import { myNextSteps, theirNextSteps, turnOf, type Detail } from "./model";
import { DueText } from "./When";

/**
 * The "whose turn" banner on every tracker (docs/spec/07 item 2; docs/spec/06 6.9): "Awaiting: <party>" from the
 * API's `whose_turn`, the next step each party owes from `awaiting`, and the stage's countdown. The same for both
 * parties apart from the wording of "you".
 */
export function WhoseTurn({ detail }: { detail: Detail }) {
  const t = useTranslations("tracker");
  const steps = useTranslations("trackerActions");
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
  // A Callout with a title (docs/platform/design/p16-design-system.md, Notices): the accent tone when it is the
  // viewer's turn, neutral otherwise; the drawn mark says current, completed or ended with the words.
  return (
    <Callout
      as="section"
      aria-labelledby="whose-turn"
      data-whose-turn={turn.kind}
      tone={yours ? "info" : "neutral"}
      title={headline}
      titleId="whose-turn"
      titleSize="lg"
      icon={
        <ChipMark
          kind={turn.kind === "ended" ? (detail.state === "CLOSED" ? "completed" : "ended") : "current"}
          className={cn(
            "mt-1 size-5",
            turn.kind === "ended" ? (detail.state === "CLOSED" ? "text-ok" : "text-ink-soft") : "text-accent",
          )}
        />
      }
    >
      <p className="flex items-center gap-2" aria-label={t("parties")}>
        <Avatar name={detail.developer_name} kind="person" size="sm" active={!ended && awaited.has("developer")} />
        <Avatar name={detail.org_name} kind="org" size="sm" active={!ended && awaited.has("org")} />
        <span className="text-sm text-ink-soft">
          {detail.developer_name} · {detail.org_name}
        </span>
      </p>
      {turn.kind === "ended" && detail.end_reason ? (
        <p className="text-ink">{t("endedBecause", { reason: t(`endReason.${detail.end_reason}`) })}</p>
      ) : null}
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
      {detail.due && turn.kind !== "ended" ? (
        <p className="text-sm">
          <DueText due={detail.due} className={detail.due.overdue ? "font-semibold text-error" : "text-ink-soft"} />
        </p>
      ) : null}
    </Callout>
  );
}
