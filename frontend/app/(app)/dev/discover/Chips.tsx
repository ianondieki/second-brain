import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { TrendIcon, WhyIcon } from "@/components/discover-icons";
import { Badge } from "@/components/ui/Badge";
import { ChevronDownIcon } from "@/components/ui/icons";
import type { RowBadges } from "@/components/ui/RowList";

/**
 * A card's Why chip: a Badge (a mark and words, never colour alone; `data-chip` lets tests count them). A card shows at
 * most two badges (docs/spec/07 item 2; Row's type refuses a third). The words come from the API ([[COPY-REVIEW]] in
 * bridge/matching).
 */
export function WhyChip({ children }: { children: ReactNode }) {
  return (
    <Badge data-chip="why" tone="neutral" icon={<WhyIcon />}>
      {children}
    </Badge>
  );
}

/**
 * The self-explaining trend badge ("Trending in ICT › Networks · Kenya: 4 companies scouting"), shown only when the
 * API sends one (cold start hides it, docs/spec/06 6.6). Neutral like every status on Discover: the accent is kept for
 * "act here" (docs/platform/design/p16-design-system.md, principle 3).
 */
export function TrendBadge({ badge }: { badge: string | null }) {
  const t = useTranslations("discover");
  if (!badge) return null;
  const detail = trendDetail(badge);
  return (
    <Badge data-badge="" tone="neutral" icon={<TrendIcon />} className="[overflow-wrap:anywhere]" title={badge}>
      {detail === null ? badge : t("trendingShort", { detail })}
    </Badge>
  );
}

/**
 * What the badge says after the niche and county it opens with ("Trending in ICT › Networks · Kenya: 4 companies
 * scouting" → "4 companies scouting"), for the card's short form (discover.trendingShort): the card's meta line
 * already says where. The sentence's last ": " splits it, so a niche or place written with one stays whole. The full
 * sentence stays in the badge's title; a badge in another shape (null here) is shown as it is.
 */
export function trendDetail(badge: string): string | null {
  const match = /^Trending in .+: (.+)$/.exec(badge);
  return match ? match[1]! : null;
}

/** A row's badges (at most two, docs/spec/07 item 2): the trend badge first, then the Why chips the caller picked. */
export function cardBadges(nodes: readonly ReactNode[]): RowBadges | undefined {
  const [first, second] = nodes.filter((node) => node !== null && node !== undefined && node !== false);
  if (first === undefined) return undefined;
  return second === undefined ? [first] : [first, second];
}

/** A list of the chips not shown on the card, under its "More about …" disclosure. */
export function ChipList({ items }: { items: readonly string[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {items.map((chip) => (
        <li key={chip} className="flex items-start gap-1.5 text-ink">
          <WhyIcon className="mt-1 size-4 shrink-0 text-accent" />
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
        "inline-flex min-h-11 cursor-pointer list-none items-center gap-1 text-sm font-semibold text-accent " +
        "hover:text-accent-strong [&::-webkit-details-marker]:hidden"
      }
    >
      {children}
      <ChevronDownIcon className="size-4 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
    </summary>
  );
}
