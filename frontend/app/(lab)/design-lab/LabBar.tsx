import Link from "next/link";

import { DIRECTION, DIRECTIONS, type DirectionKey, type Theme } from "./directions";
import { SCREENS, type ScreenKey } from "./screens";

/** The lab's own switch bar: direction, theme and screen. Not part of any direction; `?bare=1` hides it. */
export function LabBar({ direction, screen, theme }: { direction: DirectionKey; screen: ScreenKey; theme: Theme }) {
  const q = theme === "dark" ? "?theme=dark" : "";
  return (
    <nav
      data-lab-bar=""
      aria-label="Design lab"
      className="sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-black/20 bg-neutral-900 px-4 py-2 text-sm text-neutral-100"
    >
      <Link href="/design-lab" className="font-semibold text-white no-underline">
        Design lab
      </Link>
      <span className="flex gap-2">
        {DIRECTIONS.map((key) => (
          <Link
            key={key}
            href={`/design-lab/${key}/${screen}${q}`}
            aria-current={key === direction ? "page" : undefined}
            className={key === direction ? "font-semibold text-white underline" : "text-neutral-300 no-underline hover:text-white"}
          >
            {key.toUpperCase()} {DIRECTION[key].name}
          </Link>
        ))}
      </span>
      <Link href={`/design-lab/${direction}/${screen}${theme === "dark" ? "" : "?theme=dark"}`} className="text-neutral-300 no-underline hover:text-white">
        {theme === "dark" ? "Light" : "Dark"}
      </Link>
      <span className="flex flex-wrap gap-2">
        {SCREENS.map((s) => (
          <Link
            key={s.key}
            href={`/design-lab/${direction}/${s.key}${q}`}
            aria-current={s.key === screen ? "page" : undefined}
            className={s.key === screen ? "font-semibold text-white underline" : "text-neutral-300 no-underline hover:text-white"}
          >
            {s.label}
          </Link>
        ))}
      </span>
    </nav>
  );
}
