import { useTranslations } from "next-intl";

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
  return (
    <section
      aria-labelledby="whose-turn"
      data-whose-turn={turn.kind}
      className={cn(
        "border-l-4 py-3 pr-4 pl-4",
        yours
          ? "border-jacaranda bg-jacaranda-wash"
          : turn.kind === "ended"
            ? "border-line bg-transparent"
            : "border-ink-soft bg-transparent",
      )}
    >
      <p id="whose-turn" className="flex items-start gap-2 text-lg font-semibold text-ink">
        <ChipMark
          kind={turn.kind === "ended" ? (detail.state === "CLOSED" ? "completed" : "ended") : "current"}
          className={cn(
            "mt-1 size-5",
            turn.kind === "ended" ? (detail.state === "CLOSED" ? "text-ok" : "text-ink-soft") : "text-jacaranda",
          )}
        />
        <span>{headline}</span>
      </p>
      {turn.kind === "ended" && detail.end_reason ? (
        <p className="mt-1 text-ink">{t("endedBecause", { reason: t(`endReason.${detail.end_reason}`) })}</p>
      ) : null}
      {yours
        ? mine.map((command) => (
            <p key={command} className="mt-1 text-ink">
              {t("nextYou", { step: steps(`command.${command}`) })}
            </p>
          ))
        : null}
      {turn.kind === "other" || turn.kind === "both"
        ? theirs.map((command) => (
            <p key={command} className="mt-1 text-ink-soft">
              {t("nextThem", { name: other, step: steps(`command.${command}`) })}
            </p>
          ))
        : null}
      {detail.due && turn.kind !== "ended" ? (
        <p className="mt-1 text-sm">
          <DueText due={detail.due} className={detail.due.overdue ? "font-semibold text-error" : "text-ink-soft"} />
        </p>
      ) : null}
    </section>
  );
}
