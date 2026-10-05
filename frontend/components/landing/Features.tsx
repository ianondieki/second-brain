import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { TrendIcon } from "@/components/discover-icons";
import { CompaniesIcon } from "@/components/ui/icons";
import { CheckIcon, ClockIcon, Icon, type IconProps } from "@/components/ui/status-icons";
import { Sparkline } from "@/components/ui/Sparkline";
import { cn } from "@/components/ui/cn";

function BellIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 13.5V9a5 5 0 0 1 10 0v4.5l1.5 2h-13L5 13.5Z" />
      <path d="M8.25 17.25a1.9 1.9 0 0 0 3.5 0" />
    </Icon>
  );
}

/** A feature: what it lets a person do, in words, then the screen it names in miniature (decorative: aria-hidden). */
function Feature({ title, body, className, children }: { title: string; body: string; className?: string; children: ReactNode }) {
  return (
    <article className={cn("flex flex-col rounded-[1.5rem] border border-line bg-field p-5 sm:p-8", className)}>
      <h3 className="font-display text-xl font-[700] tracking-[-0.015em] text-ink lg:text-2xl">{title}</h3>
      <p className="mt-2 max-w-[48ch] text-ink-soft">{body}</p>
      <div aria-hidden="true" className="mt-6 flex-1 rounded-2xl border border-line bg-paper p-3.5 sm:mt-7 sm:p-5">
        {children}
      </div>
    </article>
  );
}

const TRENDS = [
  { key: "trend1", values: [3, 4, 4, 6, 7, 9, 12] },
  { key: "trend2", values: [5, 5, 6, 6, 8, 8, 10] },
  { key: "trend3", values: [2, 3, 3, 3, 5, 6, 7] },
] as const;

/**
 * What you can do (D-55): four of the product's screens, each in words and in miniature with labelled example data,
 * in an asymmetric grid (7 + 5 columns, then 5 + 7) so the section reads as a spread, not a row of identical cards.
 */
export async function Features() {
  const t = await getTranslations("landing.features");
  const s = await getTranslations("landing.features.sample");
  return (
    <section id="features" aria-labelledby="features-title" className="py-20 lg:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <div className="max-w-3xl">
          <h2 id="features-title" className="text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[56ch] text-lg text-ink-soft">{t("lead")}</p>
        </div>
        <div className="mt-12 grid grid-cols-1 gap-5 lg:mt-14 lg:grid-cols-12 lg:gap-6">
          <Feature title={t("discover.title")} body={t("discover.body")} className="lg:col-span-7">
            <ul className="flex flex-col divide-y divide-line">
              {TRENDS.map(({ key, values }) => (
                <li key={key} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <span className="min-w-0">
                    <span className="block font-semibold text-ink">{s(key)}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-soft">
                      {s(`${key}Niche`)}
                      <span className="inline-flex items-center gap-1 font-semibold text-accent">
                        <TrendIcon className="size-4" />
                        {s("rising")}
                      </span>
                    </span>
                  </span>
                  <Sparkline values={values} className="shrink-0 text-accent" />
                </li>
              ))}
            </ul>
          </Feature>

          <Feature title={t("briefs.title")} body={t("briefs.body")} className="lg:col-span-5">
            <div className="rounded-xl bg-field p-4 shadow-card ring-1 ring-line">
              <p className="font-semibold text-ink">{s("briefTitle")}</p>
              <p className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-ink">
                <CompaniesIcon className="size-4 text-accent" />
                {s("briefOrg")}
              </p>
              <p className="mt-2 text-sm text-ink-soft">{s("briefBudget")}</p>
              <p className="text-sm text-ink-soft">{s("briefDeadline")}</p>
            </div>
          </Feature>

          <Feature title={t("checks.title")} body={t("checks.body")} className="lg:col-span-5">
            <ul className="flex flex-col gap-3">
              {(["checkOverlap", "checkDisclosure"] as const).map((key) => (
                <li key={key} className="flex items-start gap-3 rounded-xl bg-field p-3.5 ring-1 ring-line">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ok-wash text-ok">
                    <CheckIcon className="size-4" />
                  </span>
                  <span className="pt-0.5 text-sm font-semibold text-ink">{s(key)}</span>
                </li>
              ))}
            </ul>
          </Feature>

          <Feature title={t("bell.title")} body={t("bell.body")} className="lg:col-span-7">
            <div className="flex items-start gap-4">
              <span className="relative hidden size-11 shrink-0 sm:flex items-center justify-center rounded-full bg-field text-ink ring-1 ring-line">
                <BellIcon className="size-5" />
                <span className="absolute -top-1 -right-1 flex size-5 items-center justify-center rounded-full bg-accent text-xs font-bold text-on-accent">
                  3
                </span>
              </span>
              <ul className="flex min-w-0 flex-1 flex-col divide-y divide-line">
                {([1, 2, 3] as const).map((n) => (
                  <li key={n} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                    <span className="flex min-w-0 items-baseline gap-2.5 text-sm text-ink">
                      <span className={cn("size-2 shrink-0 translate-y-[-1px] rounded-full", n < 3 ? "bg-accent" : "bg-line")} />
                      <span className={n < 3 ? "font-semibold" : undefined}>{s(`bell${n}`)}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1 pl-[1.125rem] text-xs text-ink-soft tabular-nums sm:pl-0">
                      <ClockIcon className="size-3.5" />
                      {s(`bellTime${n}`)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </Feature>
        </div>
      </div>
    </section>
  );
}
