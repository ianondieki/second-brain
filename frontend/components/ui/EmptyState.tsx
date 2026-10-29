import Link from "next/link";

import { buttonClass, standaloneLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";
import { EmptyStateFrame, type DataAttributes } from "./EmptyStateFrame";

export interface EmptyStateProps extends DataAttributes {
  sentence: string;
  action: string;
  href: string;
  /** The action is the screen's one primary button (for example "Turn on two-step sign-in" when nothing else can be done). */
  primary?: boolean;
  /** A hairline above it (default); off where a line is already there, such as under a tab strip. */
  rule?: boolean;
  className?: string;
}

/**
 * An empty or closed state: exactly one sentence and one action link (docs/spec/07 item 4, AC-UX-5). `primary` makes
 * the action the screen's one primary button.
 */
export function EmptyState({ sentence, action, href, primary = false, ...frame }: EmptyStateProps) {
  return (
    <EmptyStateFrame
      sentence={sentence}
      action={
        primary ? (
          <Link href={href} data-primary="" className={buttonClass("primary", "relative no-underline")}>
            {action}
            <LinkPending tone="current" className="absolute bottom-1.5 left-1/2 -translate-x-1/2" />
          </Link>
        ) : (
          <Link href={href} className={cn(standaloneLinkClass, "relative")}>
            {action}
            <LinkPending className="absolute bottom-0.5 left-0" />
          </Link>
        )
      }
      {...frame}
    />
  );
}
