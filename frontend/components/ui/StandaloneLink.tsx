import Link from "next/link";
import type { ComponentProps } from "react";

import { standaloneLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

/**
 * An in-app link on its own line ("Start a proposal from this problem", "Open the tracker", paging): the standalone
 * link look (its own 44 px band) with the pending hint under the words while its page is on the way (fixed size,
 * nothing moves). Links in running text stay plain `textLinkClass` links.
 */
export function StandaloneLink({ className, children, ...rest }: ComponentProps<typeof Link>) {
  return (
    <Link className={cn(standaloneLinkClass, "relative", className)} {...rest}>
      {children}
      <LinkPending className="absolute bottom-0.5 left-0" />
    </Link>
  );
}
