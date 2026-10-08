import { getTranslations } from "next-intl/server";
import type { CSSProperties } from "react";

import { CountUp } from "@/components/motion/CountUp";

/**
 * The product in four figures (D-66): constants of the product, never a usage figure. The tracker's five stages
 * (components/tracker/model.ts), the 47 counties and the 16 niches of the reference data (backend/seed/reference.yaml),
 * and no contact detail shared before an NDA (the tracker's Contact and NDA stage). Each figure is set in Bricolage
 * and counts up once as the row comes into view (CountUp); the real figure is in the text for assistive technology.
 */
export const STATS = [
  { key: "stages", value: 5 },
  { key: "counties", value: 47 },
  { key: "niches", value: 16 },
  { key: "nda", value: 0 },
] as const;

export async function Stats() {
  const t = await getTranslations("landing.stats");
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-12 sm:px-6 lg:pb-16">
      <h2 className="sr-only">{t("label")}</h2>
      <CountUp>
        <dl className="grid grid-cols-2 border-t border-line lg:grid-cols-4">
          {STATS.map(({ key, value }) => (
            <div key={key} className="flex flex-col-reverse justify-end gap-1.5 border-line pt-6 pr-4 odd:pr-6 lg:border-l lg:px-8 lg:first:border-l-0 lg:first:pl-0">
              <dt className="max-w-[18ch] text-sm leading-snug text-ink-soft">{t(key)}</dt>
              <dd className="font-figure text-[2.75rem] leading-none font-[700] tracking-[-0.03em] text-ink lg:text-[3.25rem]">
                <span aria-hidden="true" className="count" style={{ "--to": value } as CSSProperties} />
                <span className="sr-only">{value}</span>
              </dd>
            </div>
          ))}
        </dl>
      </CountUp>
    </div>
  );
}
