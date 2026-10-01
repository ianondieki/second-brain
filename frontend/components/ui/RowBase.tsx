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
  /** Each row in its own compact card, two across from 640 px (D-52), instead of hairline-separated rows. */
  cards?: boolean;
  children: ReactNode;
}

/**
 * A list of things, one Row each, each in its own <li>: a hairline above the first row and between rows (the rows
 * draw it), no box around them; or, with `cards`, each row in a compact card (D-52).
 */
export function RowList({ ordered = false, rule = true, cards = false, className, children, ...rest }: RowListProps) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag
      className={cn(
        cards
          ? "grid grid-cols-1 gap-4 sm:grid-cols-2 [&>li]:min-w-0 [&>li]:rounded-panel [&>li]:border [&>li]:border-line [&>li]:bg-field [&>li]:px-4 [&>li>article]:border-t-0 [&>li>article]:py-4"
          : "flex flex-col",
        !rule && !cards && "[&>li:first-child>article]:border-t-0",
        className,
      )}
      {...rest}
    >
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
  /** The title's id (for an aria-labelledby elsewhere). */
  titleId?: string;
  headingLevel?: 2 | 3;
  /** One line of plain facts under the title (who, where, when). */
  meta?: ReactNode;
  /** At most two status badges. */
  badges?: RowBadges;
  /** A right-aligned figure (an amount, a count), in tabular figures. */
  figure?: ReactNode;
  /**
   * "sm": the figure's column only from 640 px; below it the row's content keeps the whole width (the caller says the
   * figure in the meta line there, as the plan ladder does with its price).
   */
  figureFrom?: "sm";
  /** Anything else the row carries, after the badges (a quiet text, a secondary control). */
  children?: ReactNode;
}

/** One row of a RowList without a page of its own (an <article>): title, meta line, badges, figure, a hairline above. */
export function RowBase({
  title,
  titleId,
  headingLevel = 3,
  meta,
  badges,
  figure,
  figureFrom,
  className,
  children,
  ...rest
}: RowBaseProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article
      // The figure's column (and its 24 px gap) only when there is a figure: without one the title keeps the full width.
      className={cn(
        "relative grid border-t border-line py-5",
        figure
          ? figureFrom === "sm"
            ? "sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-6"
            : "grid-cols-[minmax(0,1fr)_auto] gap-x-6"
          : undefined,
        className,
      )}
      {...rest}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <Heading id={titleId} className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
          {title}
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
      {figure ? (
        <div className={cn("self-start text-right tabular-nums text-ink", figureFrom === "sm" && "hidden sm:block")}>
          {figure}
        </div>
      ) : null}
    </article>
  );
}
