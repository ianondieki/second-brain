import Link from "next/link";

import { PortalNavBase, type PortalNavProps } from "./PortalNavBase";
import { LinkPending } from "./ui/LinkPending";

export type { PortalNavItem, PortalNavProps } from "./PortalNavBase";

/**
 * A portal's sections with next/link and the pending hint on the tapped item (PortalNavBase draws them; P25 split the
 * markup out so a loading screen can draw the same navigation with no client code).
 */
export function PortalNav(props: PortalNavProps) {
  return <PortalNavBase {...props} Anchor={Link} pending={(className) => <LinkPending className={className} />} />;
}
