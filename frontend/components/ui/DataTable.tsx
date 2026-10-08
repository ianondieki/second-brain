import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "./cn";

export interface DataTableProps extends HTMLAttributes<HTMLTableElement> {
  /** The column headings, in order; the first column holds each row's title (a DataCell with `head`). */
  columns: readonly ReactNode[];
  children: ReactNode;
}

/**
 * A calm, dense table for the staff console (D-52): small type, hairline rows, tabular figures, no zebra and no
 * borders between cells. Under 640 px each row stacks its cells, every cell prefixed by its column's name, and the
 * header row is left out (the prefixes say the columns); a wider table scrolls sideways inside its own box, never the
 * page; from 1280 px (where the tables fit) the header row sticks under the top bar. The table roles are written out: WebKit drops a table's semantics (and its name) once its parts change
 * display, which the stacked layout does.
 */
export function DataTable({ columns, className, children, ...rest }: DataTableProps) {
  return (
    // From 1280 px the console's tables fit their column, so the box stops scrolling sideways and the header row
    // can stay under the sticky top bar while a long queue scrolls (P25); below it the box scrolls, never the page.
    <div className="w-full max-sm:contents sm:overflow-x-auto xl:overflow-x-visible">
      <table role="table" data-sticky-head="" className={cn("w-full border-collapse text-left text-sm max-sm:block", className)} {...rest}>
        <thead role="rowgroup" className="max-sm:hidden">
          <tr role="row" className="border-b border-line">
            {columns.map((column, index) => (
              <th
                key={index}
                role="columnheader"
                scope="col"
                className="py-2.5 pr-4 text-[0.8125rem] font-semibold whitespace-nowrap text-ink-soft last:pr-0 xl:sticky xl:top-16 xl:z-[1] xl:bg-field xl:shadow-[inset_0_-1px_0_var(--line)]"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody role="rowgroup" className="max-sm:block">
          {children}
        </tbody>
      </table>
    </div>
  );
}

/** One row: a hairline under it (none under the last), cells aligned to their top. */
export function DataRow({ className, children, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      role="row"
      className={cn(
        "border-b border-line align-top last:border-b-0 max-sm:block max-sm:py-3 max-sm:first:pt-0",
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

export type DataCellProps = (TdHTMLAttributes<HTMLTableCellElement> | ThHTMLAttributes<HTMLTableCellElement>) & {
  /** The column's name, said before the cell on phones (where the header row is left out). */
  label: string;
  /** The row's title cell: a row header (`th scope="row"`), shown without the column's name on phones. */
  head?: boolean;
  /** A number or a date: tabular figures. */
  figure?: boolean;
  /** Keeps the cell on one line (a short status, a date) from 640 px. */
  nowrap?: boolean;
  children?: ReactNode;
};

/** One cell; the row's title cell is a `th` with `head`. */
export function DataCell({ label, head = false, figure = false, nowrap = false, className, children, ...rest }: DataCellProps) {
  const classes = cn(
    "py-2.5 pr-4 text-left font-normal text-ink last:pr-0 max-sm:py-0.5 max-sm:pr-0",
    head ? "max-sm:mb-1 max-sm:block" : "max-sm:flex max-sm:gap-3 max-sm:before:w-32 max-sm:before:shrink-0 max-sm:before:text-ink-soft max-sm:before:content-[attr(data-label)]",
    figure && "tabular-nums",
    nowrap && "sm:whitespace-nowrap",
    className,
  );
  if (head) {
    return (
      <th role="rowheader" scope="row" data-label={label} className={classes} {...(rest as ThHTMLAttributes<HTMLTableCellElement>)}>
        {children}
      </th>
    );
  }
  return (
    <td role="cell" data-label={label} className={classes} {...(rest as TdHTMLAttributes<HTMLTableCellElement>)}>
      {children}
    </td>
  );
}

/** A row's title as its one link: no underline until hovered, a 44 px tap band inside the dense row. */
export const dataLinkClass =
  "-my-3 inline-flex items-center py-3 font-semibold text-ink no-underline [overflow-wrap:anywhere] hover:underline hover:decoration-1 hover:underline-offset-[0.2em]";
