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

/** A stat tile: the label, the figure in the display face, one meta line, and a sparkline when there is a series. Flat on the canvas. */
export function StatTile({ label, value, meta, spark, href, className, ...rest }: StatTileProps) {
  const body = (
    <>
      <span className="text-sm font-semibold text-ink-soft">{label}</span>
      <span className="mt-2 flex items-end justify-between gap-3">
        <span className="font-display text-2xl leading-none font-[720] tracking-[-0.03em] whitespace-nowrap text-ink tabular-nums">{value}</span>
        {spark ? <Sparkline values={spark} className="mb-1 shrink-0" /> : null}
      </span>
      {meta ? <span className="mt-2 text-sm text-ink-soft">{meta}</span> : null}
    </>
  );
  const classes = cn("flex min-w-0 flex-col rounded-panel border border-line bg-field p-4 sm:p-5", className);
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
