import Link from "next/link";
import { Children, Fragment, isValidElement, type HTMLAttributes, type ReactNode } from "react";

import { titleLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

export interface RowListProps extends HTMLAttributes<HTMLUListElement> {
  /** An ordered list (a ranking, a sequence) instead of a plain one. */
  ordered?: boolean;
  children: ReactNode;
}

/**
 * A list of things, one Row each, each in its own <li>: a hairline above the first row and between rows (the rows
 * draw it), no box around them (docs/platform/design/p16-design-system.md, Lists of things). Cards are not a page
 * structure.
 */
export function RowList({ ordered = false, className, children, ...rest }: RowListProps) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag className={cn("flex flex-col", className)} {...rest}>
      {Children.map(children, (child) =>
        child === null || child === undefined || child === false ? null : (
          <li key={isValidElement(child) ? child.key : undefined}>{child}</li>
        ),
      )}
    </Tag>
  );
}

/** At most two badges on a row (docs/spec/07 item 2, AC-UX-1): the type is the check, before anything runs. */
export type RowBadges = readonly [ReactNode] | readonly [ReactNode, ReactNode];

export interface RowProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /** The row's title; a link when the row has a page of its own. */
  title: ReactNode;
  /** The row's page: the whole row is the link's target (a stretched link), the title is its name. */
  href?: string;
  /**
   * Stretch the title's link over the row (default). Off for a row that holds its own controls (a disclosure, a
   * second link), which a stretched link would cover: then only the title is the link.
   */
  stretch?: boolean;
  /** The title's id (for an aria-labelledby elsewhere). */
  titleId?: string;
  headingLevel?: 2 | 3;
  /** One line of plain facts under the title (who, where, when). */
  meta?: ReactNode;
  /** At most two status badges. */
  badges?: RowBadges;
  /** A right-aligned figure (an amount, a count), in tabular figures. */
  figure?: ReactNode;
  /** Anything else the row carries, after the badges (a quiet text, a secondary control). */
  children?: ReactNode;
}

/**
 * One row of a RowList (an <article>): title (16 px, bold), meta line, badges, an optional figure on the right, 20 px
 * above and below, a hairline above. With `href` the title is a link stretched over the row, so the whole row is the
 * target.
 */
export function Row({
  title,
  href,
  stretch = true,
  titleId,
  headingLevel = 3,
  meta,
  badges,
  figure,
  className,
  children,
  ...rest
}: RowProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article
      // The figure's column (and its 24 px gap) only when there is a figure: without one the title keeps the full width.
      className={cn("relative grid border-t border-line py-5", figure ? "grid-cols-[minmax(0,1fr)_auto] gap-x-6" : undefined, className)}
      {...rest}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Heading id={titleId} className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
          {href ? (
            <Link
              href={href}
              className={cn(
                titleLinkClass,
                // Stretched, the row is the target; alone, the title keeps a 44 px band (docs/spec/07 item 6).
                stretch ? "after:absolute after:inset-0" : "-my-2.5 inline-flex min-h-11 items-center",
              )}
            >
              {title}
              {/* On the row's top hairline, not after the title: it takes no room, so titles wrap where they would. */}
              <LinkPending className="absolute -top-px left-0" />
            </Link>
          ) : (
            title
          )}
        </Heading>
        {meta ? <p className="text-sm [overflow-wrap:anywhere] text-ink-soft">{meta}</p> : null}
        {badges ? (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
            {badges.map((badge, index) => (
              <Fragment key={index}>{badge}</Fragment>
            ))}
          </div>
        ) : null}
        {children}
      </div>
      {figure ? <div className="self-start text-right tabular-nums text-ink">{figure}</div> : null}
    </article>
  );
}
