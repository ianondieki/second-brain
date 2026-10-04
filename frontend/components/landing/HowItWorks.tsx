import { getTranslations } from "next-intl/server";

import { EngagementsIcon } from "@/components/tracker/icons";
import { IdeasIcon } from "@/components/ui/icons";
import { LockIcon } from "@/components/ui/status-icons";

const STEPS = [
  { key: "publish", Icon: IdeasIcon },
  { key: "review", Icon: LockIcon },
  { key: "track", Icon: EngagementsIcon },
] as const;

const STAGES = ["review", "contact", "agreement", "implementation", "close"] as const;

/**
 * How it works (D-55): the three steps a person takes, numbered because they are a sequence, then the tracker's five
 * stages as one line, the product's spine: the same stages on both sides' screens. The line runs across from 1024 px
 * and down the left edge below.
 */
export async function HowItWorks() {
  const t = await getTranslations("landing.how");
  return (
    <section id="how" aria-labelledby="how-title" className="py-20 lg:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <div className="max-w-3xl">
          <h2 id="how-title" className="text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[56ch] text-lg text-ink-soft">{t("lead")}</p>
        </div>
        <ol className="mt-14 grid grid-cols-1 gap-10 md:grid-cols-3 md:gap-8 lg:mt-16">
          {STEPS.map(({ key, Icon }, index) => (
            <li key={key} className="flex flex-col">
              <span aria-hidden="true" className="font-display text-[3.5rem] leading-none font-[780] tracking-[-0.04em] text-accent tabular-nums">
                {index + 1}
              </span>
              <h3 className="mt-5 flex items-center gap-2.5 font-display text-xl font-[680] tracking-[-0.015em] text-ink">
                <Icon aria-hidden="true" className="size-5 shrink-0 text-accent" />
                {t(`${key}.title`)}
              </h3>
              <p className="mt-2.5 max-w-[42ch] text-ink-soft">{t(`${key}.body`)}</p>
            </li>
          ))}
        </ol>

        <div className="mt-16 rounded-[1.75rem] border border-line bg-field p-6 sm:p-8 lg:mt-20 lg:p-12">
          <h3 className="font-display text-2xl font-[700] tracking-[-0.02em] text-ink">{t("stagesTitle")}</h3>
          <p className="mt-2 max-w-[60ch] text-ink-soft">{t("stagesLead")}</p>
          <ol className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-5 lg:gap-6">
            {STAGES.map((stage, index) => (
              <li
                key={stage}
                className={
                  "relative pl-10 lg:pt-12 lg:pl-0 " +
                  // The line: down the left on phones, across the top from 1024 px; it stops at the last stage.
                  "before:absolute before:top-7 before:-bottom-8 before:left-[0.9375rem] before:w-0.5 before:bg-accent-line last:before:hidden " +
                  "lg:before:top-[0.9375rem] lg:before:right-[-1.5rem] lg:before:bottom-auto lg:before:left-8 lg:before:h-0.5 lg:before:w-auto"
                }
              >
                <span
                  aria-hidden="true"
                  className="absolute top-0 left-0 flex size-8 items-center justify-center rounded-full bg-accent font-display text-sm font-[760] text-on-accent tabular-nums"
                >
                  {index + 1}
                </span>
                <p className="font-semibold text-ink">{t(`stages.${stage}.title`)}</p>
                <p className="mt-1.5 text-sm text-ink-soft">{t(`stages.${stage}.body`)}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
