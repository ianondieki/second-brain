import Link from "next/link";
import { Fragment, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "@/components/ui/cn";
import { LinkPending } from "@/components/ui/LinkPending";
import type { RowBadges } from "@/components/ui/RowBase";

/**
 * The `sizes` of a card's photograph band: a card column is at most about 26 rem wide, and on a phone the 72 px band
 * needs no more than the smallest file (so a list of cards on Slow 4G fetches the small files, not the 1600 px ones).
 */
export const CARD_BAND = "(min-width: 640px) 26rem, 180px";

export interface ItemCardProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /** The niche's or county's photograph band (NicheBand, rendered by the server page), or the lattice. */
  band?: ReactNode;
  title: ReactNode;
  titleId?: string;
  headingLevel?: 2 | 3;
  /** The card's page: the title's link stretches over the card. */
  href?: string;
  /** One line of plain facts under the title (the niche, when it was sent). */
  meta?: ReactNode;
  /** At most two status chips (docs/spec/07 item 2), at the card's foot. */
  chips?: RowBadges;
  /** A control beside the title (the shortlist star), above the stretched link. */
  control?: ReactNode;
  /** A line at the foot beside the chips (a deadline, the proposals answering a Brief). */
  footNote?: ReactNode;
  /** Anything else the card says, under the meta line (a summary, two facts). */
  children?: ReactNode;
}

/**
 * One thing in a grid of cards on the organisation's screens (D-67, P25): a photograph band on top (decorative, the
 * niche or county is named in the meta line), the title as the card's one link, the meta line, then the chips at the
 * foot. Three parts, so in an `.item-grid` the rows of cards align their titles and their feet (subgrid). Controls
 * (the star, a chip that links to the tracker) sit above the stretched link.
 */
export function ItemCard({
  band,
  title,
  titleId,
  headingLevel = 3,
  href,
  meta,
  chips,
  control,
  footNote,
  className,
  children,
  ...rest
}: ItemCardProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article className={cn("item-card", className)} {...rest}>
      <div className="item-card-band">{band}</div>
      <div className="item-card-head">
        <div className="flex items-start justify-between gap-3">
          <Heading id={titleId} className="item-card-title">
            {href ? (
              <Link href={href} className="item-card-link">
                {title}
                <LinkPending className="absolute top-0 left-0" />
              </Link>
            ) : (
              title
            )}
          </Heading>
          {control ? <div className="relative z-[1] shrink-0">{control}</div> : null}
        </div>
        {meta ? <p className="text-sm [overflow-wrap:anywhere] text-ink-soft">{meta}</p> : null}
        {children}
      </div>
      <div className="item-card-foot">
        {chips ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {chips.map((chip, index) => (
              <Fragment key={index}>{chip}</Fragment>
            ))}
          </div>
        ) : null}
        {footNote ? <div className="text-sm text-ink-soft">{footNote}</div> : null}
      </div>
    </article>
  );
}

/** The grid of ItemCards: as many 18 rem columns as fit, each row of cards aligned part by part (subgrid). */
export function ItemGrid({ className, children, ...rest }: HTMLAttributes<HTMLUListElement> & { children: ReactNode }) {
  return (
    <ul className={cn("item-grid", className)} {...rest}>
      {children}
    </ul>
  );
}
