import { cn } from "./cn";

export interface ProgressBarProps {
  /** Completed steps out of `max`. */
  value: number;
  max: number;
  /** The accessible name ("Stage 2 of 5: Contact and NDA"). */
  label: string;
  /** Segmented for a small number of steps; continuous otherwise. */
  segments?: boolean;
  className?: string;
}

/** Progress as a bar with an accessible value; segmented when the steps are few (the tracker's five groups). */
export function ProgressBar({ value, max, label, segments = max <= 8, className }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(value, max));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={clamped}
      data-progress=""
      className={cn("flex h-1.5 w-full gap-1", className)}
    >
      {segments ? (
        Array.from({ length: max }, (_, i) => (
          <span key={i} className={cn("h-full flex-1 rounded-full", i < clamped ? "bg-accent" : "bg-line")} />
        ))
      ) : (
        <span className="h-full w-full overflow-hidden rounded-full bg-line">
          <span className="block h-full rounded-full bg-accent transition-[width] duration-(--motion-base)" style={{ width: `${(clamped / max) * 100}%` }} />
        </span>
      )}
    </div>
  );
}
