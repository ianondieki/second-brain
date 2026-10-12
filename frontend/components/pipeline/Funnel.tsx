import { getLocale, getTranslations } from "next-intl/server";

import { GROUPS, type Pipeline } from "./data";

/**
 * The conversion from one group to the next, as a whole percentage, at most 100 (more can enter the next group in the
 * window than entered this one: those that entered this one before it); none when nothing entered this one.
 */
export function conversion(from: number, to: number): number | null {
  return from > 0 ? Math.min(100, Math.round((to / from) * 100)) : null;
}

/**
 * The funnel strip above the board (P27 track B; REQ-ENG-14): how many engagements entered each stage group in the
 * window (the figures, as text first), a bar for each scaled to the largest (inline SVG in the bloom scale, light and
 * dark from the tokens; no library), and between neighbours how many went on, as a small percentage beside a sentence
 * read out instead ("8 of 12 went on to Contact and NDA"). Closed and ended in the window under it. Server-rendered.
 */
export async function Funnel({ funnel }: { funnel: Pipeline["funnel"] }) {
  const [t, tt, locale] = await Promise.all([getTranslations("pipeline"), getTranslations("tracker"), getLocale()]);
  const counts = GROUPS.map((group) => funnel.entered[group]);
  const most = Math.max(1, ...counts);
  const percent = new Intl.NumberFormat(locale === "en" ? "en-GB" : `${locale}-KE`, { style: "percent" });
  return (
    <section aria-labelledby="funnel-title" data-funnel="">
      <h2 id="funnel-title" className="text-xl text-ink">
        {t("funnelTitle", { days: funnel.window_days })}
      </h2>
      <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{t("funnelLead")}</p>
      <ol className="mt-4 grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-5">
        {GROUPS.map((group, index) => {
          const count = counts[index];
          const previous = index > 0 ? counts[index - 1] : null;
          const rate = previous === null ? null : conversion(previous, count);
          return (
            <li key={group} data-funnel-group={group} className="flex min-w-0 flex-col gap-1.5">
              <span className="flex items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-0.5">
                <span className="text-sm font-semibold text-ink-soft">{tt(`group.${group}`)}</span>
                <span className="font-figure text-2xl leading-none font-bold tabular-nums text-ink" data-entered="">
                  {count}
                </span>
              </span>
              <svg
                aria-hidden="true"
                focusable="false"
                viewBox="0 0 100 8"
                preserveAspectRatio="none"
                className="h-2 w-full overflow-visible"
              >
                <rect x="0" y="0" width="100" height="8" rx="4" className="fill-(--heat-0)" />
                <rect
                  x="0"
                  y="0"
                  width={(count / most) * 100}
                  height="8"
                  rx="4"
                  className="fill-(--heat-3)"
                  data-bar=""
                />
              </svg>
              {previous !== null ? (
                <span className="text-xs text-ink-soft" data-conversion={rate ?? "none"}>
                  <span aria-hidden="true" className="font-figure font-bold tabular-nums">
                    {rate !== null ? percent.format(rate / 100) : "–"}
                  </span>
                  <span className="sr-only">
                    {rate === null
                      ? t("conversionNone", { stage: tt(`group.${GROUPS[index - 1]}`) })
                      : count > previous
                        ? t("conversionMore", { count, from: previous, stage: tt(`group.${group}`) })
                        : t("conversion", { count, from: previous, stage: tt(`group.${group}`) })}
                  </span>
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-sm text-ink-soft" data-funnel-outcome="">
        {t("outcome", { closed: funnel.closed, ended: funnel.ended })}
      </p>
    </section>
  );
}
