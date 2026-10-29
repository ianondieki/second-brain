import type { ReactNode } from "react";

import { cn } from "./cn";
import { Illustration, type IllustrationKind } from "./Illustration";

/** `data-*` attributes an empty state carries for tests (for example `data-refusal`). */
export type DataAttributes = { [key: `data-${string}`]: string | undefined };

export interface EmptyStateFrameProps extends DataAttributes {
  sentence: ReactNode;
  /** The one action: a link (EmptyState) or, inside a form step, a button. */
  action: ReactNode;
  /** A hairline above it, as the first thing under a heading (default); off where a line is already there. */
  rule?: boolean;
  /** The drawing above the sentence (D-52); `null` for none (inside a card or a tab strip's first line). */
  illustration?: IllustrationKind | null;
  className?: string;
}

/**
 * An empty or closed state's frame: exactly one sentence and one action (docs/spec/07 item 4, AC-UX-5). Its own
 * module without next/link, for client components whose one action is a button; pages use EmptyState.
 */
export function EmptyStateFrame({ sentence, action, rule = true, illustration = "empty", className, ...data }: EmptyStateFrameProps) {
  return (
    <div
      data-empty-state=""
      {...data}
      className={cn("flex flex-col items-start gap-3", rule && "border-t border-line pt-6", className)}
    >
      {illustration ? <Illustration kind={illustration} className="mb-1 max-w-48 text-ink" /> : null}
      <p className="max-w-[60ch] text-ink">{sentence}</p>
      {action}
    </div>
  );
}
