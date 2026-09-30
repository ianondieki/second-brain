import type { ReactNode } from "react";

import { cn } from "./cn";

export interface DescriptionListProps {
  children: ReactNode;
  /** Amounts and dates: tabular figures, so the digits line up from row to row. */
  figures?: boolean;
  className?: string;
}

/**
 * Label/value pairs as a <dl>: stacked under 640 px, two columns from 640 px with the label column 9–11 rem wide on
 * every screen (docs/platform/design/p16-design-system.md, Label/value). Each pair is a Description.
 */
export function DescriptionList({ children, figures = false, className }: DescriptionListProps) {
  return (
    <dl
      className={cn(
        "grid gap-x-8 gap-y-4 sm:grid-cols-[minmax(9rem,11rem)_minmax(0,1fr)]",
        figures && "[&_dd]:tabular-nums",
        className,
      )}
    >
      {children}
    </dl>
  );
}

/** One label and its value. */
export function Description({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm font-medium text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere] text-ink">{children}</dd>
    </div>
  );
}
