import Link from "next/link";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

export interface BackLinkProps {
  href: string;
  children: ReactNode;
  /** For the rare page that hides it while a notice carries the way on (the checkout). */
  className?: string;
  [data: `data-${string}`]: string | undefined;
}

/** The link back to the list a page was opened from, on its own 44 px line above the page title. */
export function BackLink({ href, children, className, ...data }: BackLinkProps) {
  return (
    <p className={cn("-mt-2 mb-4", className)} {...data}>
      <Link href={href} className={standaloneLinkClass}>
        {children}
        <LinkPending className="ml-2" />
      </Link>
    </p>
  );
}
