import Link from "next/link";

import { titleLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";
import { RowBase, type RowBaseProps } from "./RowBase";

export { RowList, type RowBadges, type RowListProps } from "./RowBase";

export interface RowProps extends RowBaseProps {
  /** The row's page: the whole row is the link's target (a stretched link), the title is its name. */
  href?: string;
  /**
   * Stretch the title's link over the row (default). Off for a row that holds its own controls (a disclosure, a
   * second link), which a stretched link would cover: then only the title is the link.
   */
  stretch?: boolean;
  /** `data-*` markers for the title's link (the row's real tap target, for tests that measure it). */
  linkData?: { [key: `data-${string}`]: string };
}

/**
 * One row of a RowList (an <article>): title (16 px, bold), meta line, badges, an optional figure on the right, 20 px
 * above and below, a hairline above. With `href` the title is a link stretched over the row, so the whole row is the
 * target (or, with `stretch={false}`, only the title). Rows without a page, in a client component, can use RowBase
 * (./RowBase) and skip next/link.
 */
export function Row({ title, href, stretch = true, linkData, ...rest }: RowProps) {
  return (
    <RowBase
      {...rest}
      title={
        href ? (
          <Link
            href={href}
            {...linkData}
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
        )
      }
    />
  );
}
