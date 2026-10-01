import Link from "next/link";

import { ThemeToggle } from "@/components/ThemeToggle";

import { SCREENS, type ScreenKey } from "./screens";

/** The lab's own switch bar: screens and the appearance. Not part of the product; `?bare=1` hides it. */
export function LabBar({ screen }: { screen: ScreenKey }) {
  return (
    <nav data-lab-bar="" aria-label="Design lab" className="sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-field px-4 py-2 text-sm text-ink">
      <Link href="/design-lab" className="font-semibold text-ink no-underline">
        Design lab
      </Link>
      <span className="flex flex-wrap gap-3">
        {SCREENS.map((s) => (
          <Link key={s.key} href={`/design-lab/${s.key}`} aria-current={s.key === screen ? "page" : undefined} className={s.key === screen ? "font-semibold text-accent underline" : "text-ink-soft no-underline hover:text-ink"}>
            {s.label}
          </Link>
        ))}
      </span>
      <ThemeToggle className="ml-auto" />
    </nav>
  );
}
