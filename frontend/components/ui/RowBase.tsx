import { Children, Fragment, isValidElement, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";

// The link-free half of RowList (docs/platform/design/p16-design-system.md, Lists of things): the list and a row
// whose title is already rendered. Its own module without next/link or LinkPending, so a client component that lists
// rows without pages (the scout Preview) does not bundle them; rows with a page use Row from ./RowList.

export interface RowListProps extends HTMLAttributes<HTMLUListElement> {
  /** An ordered list (a ranking, a sequence) instead of a plain one. */
  ordered?: boolean;
  /** The hairline above the first row (default); off where a line is already there, such as under a tab strip. */
  rule?: boolean;
  children: ReactNode;
}

/**
 * A list of things, one Row each, each in its own <li>: a hairline above the first row and between rows (the rows
 * draw it), no box around them. Cards are not a page structure.
 */
export function RowList({ ordered = false, rule = true, className, children, ...rest }: RowListProps) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag className={cn("flex flex-col", !rule && "[&>li:first-child>article]:border-t-0", className)} {...rest}>
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

export interface RowBaseProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /** The row's title as rendered (Row puts its stretched link here). */
  title: ReactNode;
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

/** One row of a RowList without a page of its own (an <article>): title, meta line, badges, figure, a hairline above. */
export function RowBase({ title, headingLevel = 3, meta, badges, figure, className, children, ...rest }: RowBaseProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article
      className={cn("relative grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-t border-line py-5", className)}
      {...rest}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Heading className="text-base font-semibold [overflow-wrap:anywhere] text-ink">{title}</Heading>
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
