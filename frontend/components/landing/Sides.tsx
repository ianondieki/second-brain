import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass } from "@/components/ui/Button";
import { CompaniesIcon, IdeasIcon } from "@/components/ui/icons";
import { CheckIcon } from "@/components/ui/status-icons";
import { cn } from "@/components/ui/cn";

const SIDES = [
  { side: "developers", Icon: IdeasIcon, tone: "bg-paper" },
  { side: "organisations", Icon: CompaniesIcon, tone: "on-night bg-night" },
] as const;

/**
 * Who it is for (D-55): the two sides as two panels of equal weight and different surfaces, the developer's on the
 * canvas, the organisation's on the night band, each with what it gets and where to start. The organisation's panel
 * is the target of the top bar's "For organisations".
 */
export async function Sides() {
  const t = await getTranslations("landing.who");
  return (
    <section aria-labelledby="who-title" className="border-y border-line bg-field py-20 lg:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <h2 id="who-title" className="text-3xl text-ink lg:text-4xl">
          {t("title")}
        </h2>
        <div className="mt-12 grid grid-cols-1 gap-5 lg:mt-14 lg:grid-cols-2 lg:gap-6">
          {SIDES.map(({ side, Icon, tone }) => (
            <article
              key={side}
              id={side}
              aria-labelledby={`who-${side}`}
              className={cn("flex flex-col rounded-[1.75rem] p-7 sm:p-10", tone, side === "developers" && "border border-line")}
            >
              <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-2xl bg-accent-wash text-accent">
                <Icon className="size-6" />
              </span>
              <h3 id={`who-${side}`} className="mt-6 font-display text-2xl font-[720] tracking-[-0.02em] text-ink lg:text-3xl">
                {t(`${side}.title`)}
              </h3>
              <ul className="mt-6 flex flex-col gap-4 text-ink lg:text-lg">
                {([1, 2, 3] as const).map((n) => (
                  <li key={n} className="flex gap-3">
                    <CheckIcon aria-hidden="true" className="mt-1 size-5 shrink-0 text-accent" />
                    <span>{t(`${side}.point${n}`)}</span>
                  </li>
                ))}
              </ul>
              <Link href="/signup" className={cn(standaloneLinkClass, "mt-8 self-start text-lg")}>
                {t(`${side}.action`)}
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
