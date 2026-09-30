import Link from "next/link";

import { cn } from "@/components/ui/cn";

export interface ViewTab {
  key: string;
  label: string;
  href: string;
}

/**
 * A console queue's views (Moderation: Open · Decided; Claims: Review · In progress · Closed) as links, so each is its
 * own address and works before the page's scripts load (like the Inbox's tabs). The current one carries
 * aria-current="page" and a bar, not colour alone; each is a 44 px target.
 */
export function ViewTabs({ label, tabs, current }: { label: string; tabs: readonly ViewTab[]; current: string }) {
  return (
    <nav aria-label={label} className="border-b border-line">
      <ul className="flex gap-1 overflow-x-auto">
        {tabs.map(({ key, label: text, href }) => (
          <li key={key}>
            <Link
              href={href}
              aria-current={key === current ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center border-b-2 px-3 font-semibold whitespace-nowrap no-underline",
                key === current ? "border-jacaranda text-jacaranda" : "border-transparent text-ink-soft hover:text-ink",
              )}
            >
              {text}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
