import type { ReactNode } from "react";

import { badgeBase } from "@/components/ui/Badge";
import { cn } from "@/components/ui/cn";

import type { ChipKind } from "./model";

// The tracker's status marks (docs/spec/06 6.9): ✓ Completed · ● Current · ○ Pending · ⏸ On hold · ⚠ Overdue ·
// ✕ Ended. Each is a drawn mark, a word and a colour together, never colour alone (docs/spec/07 item 6). The marks
// are SVG, not text glyphs, so they look the same on every phone's fonts.

export const CHIP_TONE: Record<ChipKind, string> = {
  completed: "text-ok",
  current: "text-accent",
  pending: "text-ink-soft",
  onHold: "text-ink",
  overdue: "text-error",
  ended: "text-ink-soft",
};

/** The mark alone (decorative: the word next to it carries the meaning). */
export function ChipMark({ kind, className }: { kind: ChipKind; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      data-mark={kind}
      className={cn("shrink-0", className)}
    >
      {kind === "completed" ? (
        <>
          <circle cx="10" cy="10" r="8" fill="currentColor" stroke="none" />
          <path d="m6.5 10.25 2.4 2.4 4.6-5.1" stroke="var(--paper)" strokeWidth="2" />
        </>
      ) : kind === "current" ? (
        <>
          <circle cx="10" cy="10" r="7.25" />
          <circle cx="10" cy="10" r="3.75" fill="currentColor" stroke="none" />
        </>
      ) : kind === "pending" ? (
        <circle cx="10" cy="10" r="7.25" />
      ) : kind === "onHold" ? (
        <>
          <circle cx="10" cy="10" r="7.25" />
          <path d="M8.25 7v6M11.75 7v6" strokeWidth="2" />
        </>
      ) : kind === "overdue" ? (
        <>
          <path d="M10 2.75 18 16.75H2Z" fill="currentColor" stroke="currentColor" strokeWidth="1.5" />
          <path d="M10 7.5v4" stroke="var(--paper)" strokeWidth="2" />
          <path d="M10 14.1v.05" stroke="var(--paper)" strokeWidth="2.25" />
        </>
      ) : (
        <>
          <circle cx="10" cy="10" r="7.25" />
          <path d="m7.25 7.25 5.5 5.5M12.75 7.25l-5.5 5.5" />
        </>
      )}
    </svg>
  );
}

/**
 * A mark and its words in the chip's colour (`data-chip` lets tests count a card's chips): the Badge's shape
 * (components/ui/Badge.tsx) with the tracker's six marks and tones, "On hold" in ink among them.
 */
export function Chip({ kind, children, className }: { kind: ChipKind; children: ReactNode; className?: string }) {
  return (
    <span data-chip={kind} className={cn(badgeBase, CHIP_TONE[kind], className)}>
      <ChipMark kind={kind} className="size-4" />
      <span className="min-w-0">{children}</span>
    </span>
  );
}
