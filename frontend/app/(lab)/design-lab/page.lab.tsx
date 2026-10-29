import type { Metadata } from "next";
import Link from "next/link";

import { SCREENS } from "./screens";

export const metadata: Metadata = { title: "Design lab", robots: { index: false } };

/** The lab's front page (development only): the product's screens on fixture data, for screenshots and review. */
export default function DesignLabIndex() {
  return (
    <main id="main" className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 lg:py-16">
      <h1 className="text-2xl text-ink lg:text-3xl">Design lab</h1>
      <p className="mt-2 max-w-[60ch] text-ink-soft">
        Development only. The product&apos;s own components on fixture data, no API. Add <code>?bare=1</code> to hide the switch bar;
        the appearance setting (system, light, dark) is the app&apos;s own.
      </p>
      <ul className="mt-8 flex flex-col divide-y divide-line border-y border-line">
        {SCREENS.map((s) => (
          <li key={s.key}>
            <Link href={`/design-lab/${s.key}`} className="flex min-h-12 items-center font-semibold text-accent underline">
              {s.label}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
