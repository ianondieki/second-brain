import { getTranslations } from "next-intl/server";
import type { CSSProperties } from "react";

const STEPS = ["publish", "review", "track"] as const;

/** Its place in the reveal (globals.css .reveal): each card a little after the one before. */
const order = (i: number) => ({ "--i": i }) as CSSProperties;

/**
 * How it works (D-66, after Basix's three steps): three numbered cards, because the steps are a sequence, each with a
 * rule carrying its number in the mono face, the step in words and a mono chip quoting the product's own terms. The
 * cards reveal as they scroll into view where the browser has scroll-driven animations (CSS only; in place elsewhere
 * and under reduced motion).
 */
export async function HowItWorks() {
  const t = await getTranslations("landing.how");
  return (
    <section id="how" aria-labelledby="how-title" className="border-y border-line bg-field py-20 lg:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <div className="grid grid-cols-1 gap-x-12 gap-y-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-end">
          <div>
            <p className="eyebrow">{t("eyebrow")}</p>
            <h2 id="how-title" className="mt-4 max-w-[22ch] text-3xl text-ink lg:text-4xl">
              {t("title")}
            </h2>
          </div>
          <p className="max-w-[46ch] text-ink-soft lg:pb-1.5">{t("lead")}</p>
        </div>
        <ol className="mt-12 grid grid-cols-1 gap-4 md:grid-cols-3 md:gap-5 lg:mt-14">
          {STEPS.map((key, index) => (
            <li key={key} className="reveal flex flex-col rounded-[1.25rem] border border-line bg-paper p-6 sm:p-7" style={order(index)}>
              <span aria-hidden="true" className="flex items-center gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent font-mono text-sm text-on-accent">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="h-px flex-1 bg-line" />
              </span>
              <h3 className="mt-6 font-display text-[1.375rem] leading-snug font-[580] tracking-[-0.01em] text-ink">{t(`${key}.title`)}</h3>
              <p className="mt-2.5 flex-1 text-ink-soft">{t(`${key}.body`)}</p>
              <p className="mt-6 self-start rounded-lg border border-line bg-field px-3 py-1.5 font-mono text-xs text-ink-soft">{t(`${key}.chip`)}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
