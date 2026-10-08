import Link from "next/link";
import type { ReactNode } from "react";

import { TopBarBase } from "./TopBarBase";

/** Skip link plus the top bar: the working name (a link home) on the left, at most one control on the right. */
export async function TopBar({ homeHref = "/", children, sticky = false }: { homeHref?: string; children?: ReactNode; sticky?: boolean }) {
  return (
    <TopBarBase homeHref={homeHref} Anchor={Link} sticky={sticky}>
      {children}
    </TopBarBase>
  );
}
