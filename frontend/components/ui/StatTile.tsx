import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "./cn";
import { Sparkline } from "./Sparkline";

export interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  /** One short line under the value ("2 drafts", "due 7 Oct"). */
  meta?: ReactNode;
  /** A recent series, when the data exists; otherwise the tile shows the value alone. */
  spark?: readonly number[];
  href?: string;
  className?: string;
  "data-stat"?: string;
}

/** A stat tile: the label, the figure, one meta line, and a sparkline when there is a series. Cards sit a hair above the paper. */
export function StatTile({ label, value, meta, spark, href, className, ...rest }: StatTileProps) {
  const body = (
    <>
      <span className="text-sm font-medium text-ink-soft">{label}</span>
      <span className="mt-1 flex items-end justify-between gap-3">
        <span className="text-lg font-semibold whitespace-nowrap text-ink tabular-nums sm:text-xl">{value}</span>
        {spark ? <Sparkline values={spark} className="mb-1 shrink-0" /> : null}
      </span>
      {meta ? <span className="mt-0.5 text-sm text-ink-soft">{meta}</span> : null}
    </>
  );
  const classes = cn("flex min-w-0 flex-col rounded-panel border border-line bg-field p-4 shadow-card", className);
  return href ? (
    <Link href={href} className={cn(classes, "no-underline hover:border-accent-line")} {...rest}>
      {body}
    </Link>
  ) : (
    <div className={classes} {...rest}>
      {body}
    </div>
  );
}
