import Link from "next/link";
import type { ReactNode } from "react";

import { TopBarBase } from "./TopBarBase";

/** Skip link plus the top bar: the working name (a link home) on the left, at most one control on the right. */
export async function TopBar({
  homeHref = "/",
  children,
  sticky = false,
  bleed = false,
}: {
  homeHref?: string;
  children?: ReactNode;
  sticky?: boolean;
  /** The content runs on to the window's right edge (SignedInShell `bleed`): the bar's frame does too. */
  bleed?: boolean;
}) {
  return (
    <TopBarBase homeHref={homeHref} Anchor={Link} sticky={sticky} bleed={bleed}>
      {children}
    </TopBarBase>
  );
}
