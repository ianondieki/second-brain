import { useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";

import type { InboxItem } from "./data";

type State = NonNullable<InboxItem["engagement"]>["state"];

const ENDED: ReadonlySet<State> = new Set(["DECLINED", "WITHDRAWN", "TERMINATED", "EXPIRED", "CLOSED"]);

/**
 * Where the proposal stands with this organisation: the card's one chip (docs/spec/07 item 2, at most two). A dot and
 * words (status is never colour alone): filled jacaranda while it is new, an open ring once it has ended.
 *
 * The tracker screen does not exist yet (REQ-ENG-03): when it lands, this becomes the link to
 * /org/engagements/{engagement.id}. Until then it names the stage only.
 */
export function StageChip({ engagement, className }: { engagement: InboxItem["engagement"]; className?: string }) {
  const t = useTranslations("inbox");
  const state: State = engagement?.state ?? "SUBMITTED";
  const tone = state === "SUBMITTED" ? "new" : ENDED.has(state) ? "ended" : "open";
  return (
    <span
      data-chip="stage"
      data-engagement={engagement?.id}
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-semibold",
        tone === "ended" ? "text-ink-soft" : "text-jacaranda",
        className,
      )}
    >
      <svg aria-hidden="true" focusable="false" width="10" height="10" viewBox="0 0 10 10" className="shrink-0">
        <circle
          cx="5"
          cy="5"
          r="3.75"
          fill={tone === "new" ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
      {t("stage", { state })}
    </span>
  );
}
