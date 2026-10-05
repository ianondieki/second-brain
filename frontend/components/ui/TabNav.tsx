import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

export interface TabNavItem {
  key: string;
  label: ReactNode;
  href: string;
}

export interface TabNavProps {
  /** The tabs' accessible name ("Inbox sections"): required, a page can hold more than one <nav>. */
  label: string;
  items: readonly TabNavItem[];
  current: string;
  className?: string;
}

/**
 * Views of one page as links, so each is its own address and works before any script loads
 * (docs/platform/design/p16-design-system.md, Tabs). The current one carries aria-current="page", the accent colour,
 * weight and a 2 px bar (never colour alone); each is a 44 px target; at 360 px the strip scrolls sideways inside
 * itself rather than widening the page.
 */
export function TabNav({ label, items, current, className }: TabNavProps) {
  return (
    <nav aria-label={label} className={cn("border-b border-line", className)}>
      {/* Tighter under 640 px, so the Discover, tracker and Inbox strips fit 360 px without scrolling. */}
      <ul className="-mb-px flex gap-0 overflow-x-auto sm:gap-1">
        {items.map(({ key, label: text, href }) => {
          const active = key === current;
          return (
            <li key={key} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  // The ring sits inside the tab: the strip scrolls sideways inside its own box, which would clip an outset ring.
                  "relative inline-flex min-h-11 items-center border-b-2 px-2 whitespace-nowrap no-underline [--focus-offset:-3px] sm:px-3",
                  "transition-colors duration-150 ease-out",
                  active
                    ? "border-accent font-bold text-ink"
                    : "border-transparent font-semibold text-ink-soft hover:border-accent-line hover:text-ink",
                )}
              >
                {text}
                <LinkPending className="absolute bottom-1.5 left-1/2 -translate-x-1/2" />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
