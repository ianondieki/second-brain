import Link from "next/link";
import { useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";

import type { InboxItem } from "./data";
import { stageKey } from "./labels";

type State = NonNullable<InboxItem["engagement"]>["state"];

const ENDED: ReadonlySet<State> = new Set(["DECLINED", "WITHDRAWN", "TERMINATED", "EXPIRED", "CLOSED"]);

/**
 * Where the proposal stands with this organisation: the card's one chip (docs/spec/07 item 2, at most two). A dot and
 * words (status is never colour alone): filled jacaranda while it is new, an open ring once it has ended.
 * With an engagement and `href` (its tracker, REQ-ENG-03), the chip is the link to /org/engagements/{id}.
 */
export function StageChip({
  engagement,
  href,
  className,
}: {
  engagement: InboxItem["engagement"];
  href?: string;
  className?: string;
}) {
  const t = useTranslations("inbox");
  const state: State = engagement?.state ?? "SUBMITTED";
  const tone = state === "SUBMITTED" ? "new" : ENDED.has(state) ? "ended" : "open";
  const look = cn(
    "inline-flex items-center gap-1.5 text-sm font-semibold",
    tone === "ended" ? "text-ink-soft" : "text-jacaranda",
    className,
  );
  const content = (
    <>
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
      {t(stageKey(state))}
    </>
  );
  if (engagement && href) {
    return (
      <Link
        href={href}
        data-chip="stage"
        data-engagement={engagement.id}
        className={cn(look, "-my-2 min-h-11 py-2 underline decoration-1 underline-offset-[0.2em] hover:decoration-2")}
      >
        {content}
      </Link>
    );
  }
  return (
    <span data-chip="stage" data-engagement={engagement?.id} className={look}>
      {content}
    </span>
  );
}
