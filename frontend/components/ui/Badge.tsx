import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";

export type BadgeTone = "accent" | "warm" | "ok" | "error" | "neutral";

/**
 * The shape every status mark shares: an icon and words, small and bold. The icon sits on the first line (a 16 px
 * mark 2 px down a 20 px line: centred on one line, and still beside the first line when a long badge wraps).
 */
export const badgeBase =
  "inline-flex items-start gap-1.5 text-sm font-semibold [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0";

const tones: Record<BadgeTone, string> = {
  accent: "text-accent",
  warm: "text-warm",
  ok: "text-ok",
  error: "text-error",
  neutral: "text-ink-soft",
};

// Filled only for the one "Your turn" / "Needs you" marker of a row (the warm accent, D-52); rounded-full is kept for it and the avatar.
const solidTones: Record<BadgeTone, string> = {
  accent: "bg-accent text-on-accent",
  warm: "bg-warm text-on-warm",
  ok: "bg-ok text-on-ok",
  error: "bg-error text-on-accent",
  neutral: "bg-ink text-paper",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  /** The row's one "Your turn" / "Needs you" marker: filled in the tone. At most one per row. */
  solid?: boolean;
  /** A drawn mark before the words (decorative, aria-hidden): the words carry the meaning, never the colour alone. */
  icon?: ReactNode;
  /** The words. Required: a badge is never colour or an icon alone (docs/spec/07 item 6). */
  children: ReactNode;
  "data-chip"?: string;
  "data-badge"?: string;
}

/**
 * A status: icon + words + tone, the same everywhere (docs/platform/design/p16-design-system.md, Status). A row
 * carries at most two (docs/spec/07 item 2; Row takes a tuple of at most two). `data-chip` and `data-badge` pass
 * through, so tests that count a card's chips keep working.
 */
export function Badge({ tone = "neutral", solid = false, icon, className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(badgeBase, solid ? cn("rounded-full px-2.5 py-0.5", solidTones[tone]) : tones[tone], className)}
      {...rest}
    >
      {icon}
      <span className="min-w-0">{children}</span>
    </span>
  );
}
