import { Children, isValidElement, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "@/components/ui/cn";
import { NicheBand } from "@/components/ui/NicheBand";

/**
 * Discover's lists (P20, P25): compact cards two across from 1280 px, each as tall as its row. With an odd number the first
 * (the list's top item: rising fastest, or newest) takes the whole row, so a card never sits alone under two. An
 * ordered list: the order is the ranking.
 */
export function CardList({ children, className, ...rest }: HTMLAttributes<HTMLOListElement> & { children: ReactNode }) {
  const items = Children.toArray(children).filter(isValidElement);
  return (
    <ol
      className={cn(
        // Two across from 1280 px (P25): narrower, each card's photograph band and text keep their measure.
        "grid grid-cols-1 gap-4 xl:grid-cols-2 xl:gap-5 [&>li]:min-w-0",
        items.length > 1 && items.length % 2 === 1 && "xl:[&>li:first-child]:col-span-2",
        className,
      )}
      {...rest}
    >
      {items.map((child) => (
        <li key={child.key}>{child}</li>
      ))}
    </ol>
  );
}

/** One card of a Discover list: white with a hairline, the panel radius, its foot pushed to the bottom. */
export const discoverCardClass =
  "relative flex h-full min-w-0 flex-col rounded-panel border border-line bg-field p-4 transition-[border-color] duration-(--motion-fast) hover:border-accent-line sm:p-5";

/** The card's title: the text face at 18 px, the link to the problem's page (or plain words when it has none). */
export const discoverTitleClass = "text-lg leading-snug font-semibold text-pretty [overflow-wrap:anywhere] text-ink";

/**
 * The card's foot, at the bottom of the card whatever the content above: a hairline, then the facts on the left and
 * the way to start on the right (wrapping on a phone).
 */
export function CardFoot({ children }: { children: ReactNode }) {
  return (
    <div className="mt-auto pt-3">
      <p className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-t border-line pt-3 text-sm text-ink-soft">{children}</p>
    </div>
  );
}

/**
 * The card's photograph band (P25, D-67): its niche's photograph (or the county's for the public sector), or the
 * lattice where there is none, bleeding to the card's edges at its top. Decorative: the niche is named on the card.
 */
export function CardBand({ niche, county }: { niche?: { slug: string } | null; county?: string | null }) {
  return <NicheBand niche={niche?.slug} county={county} className="-mx-4 -mt-4 mb-4 h-14 rounded-t-[15px] rounded-b-none sm:-mx-5 sm:-mt-5 sm:h-16" />;
}
