import type { ReactNode } from "react";

import { cn } from "@/components/ui/cn";

/**
 * A console queue on its sheet (P20, p20-design-system.md Portals): the table on one white surface with a hairline,
 * raised when it is the work the screen exists for (the open queue), flat when it is a record (recent runs). An
 * optional summary line sits at its head, over a hairline, so the queue's size and urgency read before its rows.
 */
export function QueueSurface({
  summary,
  raised = true,
  className,
  children,
}: {
  summary?: ReactNode;
  raised?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("rounded-panel border border-line bg-field", raised && "shadow-card", className)}>
      {summary ? <div className="border-b border-line px-4 py-4 sm:px-6">{summary}</div> : null}
      <div className="px-4 py-3 sm:px-6 sm:py-2">{children}</div>
    </div>
  );
}

export interface SummaryFigure {
  key: string;
  label: string;
  value: ReactNode;
}

/**
 * The queue at a glance: two or three figures in the display face with tabular numerals, label above figure. On a
 * phone each figure is a line (label left, figure right); from 640 px they stand side by side between hairlines.
 */
export function QueueSummary({ figures }: { figures: readonly SummaryFigure[] }) {
  return (
    <dl data-queue-summary="" className="grid grid-cols-1 gap-y-2 sm:auto-cols-fr sm:grid-flow-col sm:divide-x sm:divide-line">
      {figures.map((figure) => (
        <div
          key={figure.key}
          data-summary={figure.key}
          className="flex items-baseline justify-between gap-4 sm:flex-col sm:justify-start sm:gap-1 sm:px-6 sm:first:pl-0 sm:last:pr-0"
        >
          <dt className="text-sm font-medium text-ink-soft">{figure.label}</dt>
          <dd className="font-display text-xl leading-none font-[680] tracking-[-0.02em] text-ink tabular-nums sm:text-2xl">
            {figure.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
