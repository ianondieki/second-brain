import type { ReactNode } from "react";

import { Icon } from "@/components/ui/status-icons";

/**
 * An overflow menu for the steps a person rarely takes (Block, Leave thread): a native disclosure, so it needs no
 * script, opens with Enter or Space and keeps the reading order. Its button is a 44 px square with three dots and an
 * accessible name; `describedBy` names what it is about (a row's title). The items are buttons the caller gives.
 * The page closes it on Escape, an outside press or an item's press (./overflow-close.ts). `align="end"` opens it
 * leftward from its button, for a button near the right edge (it stays inside a 360 px screen).
 */
export function Overflow({
  label,
  describedBy,
  align = "start",
  children,
  ...rest
}: {
  label: string;
  describedBy?: string;
  align?: "start" | "end";
  children: ReactNode;
} & { [key: `data-${string}`]: string }) {
  return (
    <details className="group relative" data-overflow="" {...rest}>
      <summary
        aria-label={label}
        aria-describedby={describedBy}
        className="flex size-11 cursor-pointer list-none items-center justify-center rounded-full border border-line bg-field text-ink hover:border-accent-line group-open:border-accent [&::-webkit-details-marker]:hidden"
      >
        <Icon className="size-5">
          <circle cx="4.5" cy="10" r="1.1" fill="currentColor" />
          <circle cx="10" cy="10" r="1.1" fill="currentColor" />
          <circle cx="15.5" cy="10" r="1.1" fill="currentColor" />
        </Icon>
      </summary>
      <div
        className={`absolute top-full z-10 mt-2 flex min-w-44 flex-col rounded-control border border-line bg-field p-1 shadow-overlay ${align === "end" ? "right-0" : "left-0"}`}
      >
        {children}
      </div>
    </details>
  );
}

/** An item of an Overflow menu: a full-width 44 px button; `danger` for an ending step (in words and colour). */
export const overflowItemClass =
  "flex min-h-11 w-full items-center rounded-[0.5rem] px-3 text-left font-semibold text-ink hover:bg-paper focus-visible:outline-2 focus-visible:outline-accent";
