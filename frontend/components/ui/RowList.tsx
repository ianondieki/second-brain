import Link from "next/link";

import { LinkPending } from "./LinkPending";
import { RowBase, type RowBaseProps } from "./RowBase";

export { RowList, type RowBadges, type RowListProps } from "./RowBase";

export interface RowProps extends RowBaseProps {
  /** The row's page: the whole row is the link's target (a stretched link), the title is its name. */
  href?: string;
  /** `data-*` markers for the title's link (the row's real tap target, for tests that measure it). */
  linkData?: { [key: `data-${string}`]: string };
}

/**
 * One row of a RowList (an <article>): title (16 px, bold), meta line, badges, an optional figure on the right, 20 px
 * above and below, a hairline above. With `href` the title is a link stretched over the row, so the whole row is the
 * target. Rows without a page, in a client component, can use RowBase (./RowBase) and skip next/link.
 */
export function Row({ title, href, linkData, ...rest }: RowProps) {
  return (
    <RowBase
      {...rest}
      title={
        href ? (
          <Link
            href={href}
            {...linkData}
            className="underline decoration-line decoration-1 underline-offset-4 after:absolute after:inset-0 hover:decoration-jacaranda"
          >
            {title}
            <LinkPending className="ml-2 align-middle" />
          </Link>
        ) : (
          title
        )
      }
    />
  );
}
