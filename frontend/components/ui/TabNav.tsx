import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "./cn";

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
      <ul className="-mb-px flex gap-1 overflow-x-auto">
        {items.map(({ key, label: text, href }) => {
          const active = key === current;
          return (
            <li key={key} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-11 items-center border-b-2 px-3 whitespace-nowrap no-underline",
                  "transition-colors duration-150 ease-out",
                  active
                    ? "border-jacaranda font-semibold text-jacaranda"
                    : "border-transparent font-medium text-ink-soft hover:border-line hover:text-ink",
                )}
              >
                {text}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
