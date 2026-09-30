import Link from "next/link";

import { PortalNavBase, type PortalNavBaseProps } from "./PortalNavBase";

export type { PortalNavItem } from "./PortalNavBase";
export type PortalNavProps = Omit<PortalNavBaseProps, "Anchor">;

/**
 * A portal's sections with next/link (PortalNavBase: bottom tabs under 1024 px, a left rail from 1024 px, the current
 * section marked by colour, weight and a bar, and no phone tab bar for a single section).
 */
export function PortalNav(props: PortalNavProps) {
  return <PortalNavBase {...props} Anchor={Link} />;
}
