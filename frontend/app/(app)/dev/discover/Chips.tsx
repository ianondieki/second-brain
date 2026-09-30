import type { ReactNode } from "react";

import { TrendIcon, WhyIcon } from "@/components/discover-icons";
import { cn } from "@/components/ui/cn";
import { ChevronDownIcon } from "@/components/ui/icons";

/**
 * A card's chips (docs/spec/07 item 2: at most two; the caller picks them). Each is a mark and words, never colour
 * alone; `data-chip` lets tests count them. The words come from the API ([[COPY-REVIEW]] in bridge/matching).
 */
export function Chips({ items, children, className }: { items: readonly string[]; children?: ReactNode; className?: string }) {
  if (items.length === 0 && !children) return null;
  return (
    <ul data-chips="" className={cn("flex flex-wrap gap-x-4 gap-y-1", className)}>
      {children}
      {items.map((chip) => (
        <li key={chip} data-chip="why" className="inline-flex items-start gap-1.5 text-sm font-medium text-ink">
          <WhyIcon className="mt-0.5 size-4 shrink-0 text-jacaranda" />
          <span className="min-w-0">{chip}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The self-explaining trend badge ("Trending in ICT › Networks · Kenya: 4 companies scouting"), a sentence rather than
 * a chip, shown only when the API sends one (cold start hides it, docs/spec/06 6.6).
 */
export function TrendBadge({ badge }: { badge: string | null }) {
  if (!badge) return null;
  return (
    <p data-badge="" className="flex items-start gap-1.5 text-sm font-semibold text-jacaranda">
      <TrendIcon className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0 [overflow-wrap:anywhere]">{badge}</span>
    </p>
  );
}

/** A list of the chips not shown on the card, under its "More about …" disclosure. */
export function ChipList({ items }: { items: readonly string[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {items.map((chip) => (
        <li key={chip} className="flex items-start gap-1.5 text-ink">
          <WhyIcon className="mt-1 size-4 shrink-0 text-jacaranda" />
          <span className="min-w-0">{chip}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The summary of a card's "More about …" disclosure: quieter than the card's action (no underline), with a chevron
 * that turns when open, like the filters' disclosure. The parent <details> needs the `group` class.
 */
export function MoreSummary({ children }: { children: ReactNode }) {
  return (
    <summary
      className={
        "inline-flex min-h-11 cursor-pointer list-none items-center gap-1 text-sm font-semibold text-jacaranda " +
        "hover:text-[color-mix(in_oklab,var(--jacaranda)_84%,var(--ink))] [&::-webkit-details-marker]:hidden"
      }
    >
      {children}
      <ChevronDownIcon className="size-4 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
    </summary>
  );
}
