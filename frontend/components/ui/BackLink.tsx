import Link from "next/link";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "./Button";

/** The link back to the list a page was opened from, on its own 44 px line above the page title. */
export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <p className="-mt-2 mb-4">
      <Link href={href} className={standaloneLinkClass}>
        {children}
      </Link>
    </p>
  );
}
