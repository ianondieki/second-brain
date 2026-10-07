import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { preload } from "react-dom";

import { ButtonLink } from "@/components/ui/ButtonLink";
import { Lattice } from "@/components/ui/Lattice";

import { HeroComposition } from "./HeroComposition";
import { Stats } from "./Stats";

/**
 * The hero on paper (D-66, after D-55's night hero): the eyebrow, the promise set large in Fraunces with its one
 * italic accent phrase in bloom, the lead, the one primary action and a quieter way to check a certificate; the
 * product panel beside it (below it on phones); then the stats row of product constants. The band ends on the kanga
 * lattice. The italic face is preloaded here only: no other page sets it.
 */
export async function Hero() {
  const t = await getTranslations("landing");
  preload("/fonts/fraunces-italic-v1.woff2", { as: "font", type: "font/woff2", crossOrigin: "anonymous", fetchPriority: "high" });
  return (
    <section aria-labelledby="hero-title" className="relative isolate overflow-hidden">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-12 px-4 pt-12 pb-14 sm:px-6 sm:pt-16 lg:pt-20 xl:grid-cols-[minmax(0,0.86fr)_minmax(0,1.14fr)] xl:items-center xl:gap-12 xl:pb-16">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1
            id="hero-title"
            className="mt-5 max-w-[14ch] text-[2.75rem] leading-[1.02] tracking-[-0.025em] text-ink sm:text-[3.75rem] lg:text-[4.5rem] lg:leading-[0.98] xl:text-[4rem]"
          >
            {t.rich("title", { accent: (chunks) => <em className="hero-accent">{chunks}</em> })}
          </h1>
          <p className="mt-7 max-w-[50ch] text-lg text-ink-soft">{t("lead")}</p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <ButtonLink href="/signup" variant="primary">
              {t("signUp")}
            </ButtonLink>
            <ButtonLink href="/verify" variant="secondary">
              {t("hero.check")}
            </ButtonLink>
          </div>
          <p className="mt-6 text-ink-soft">
            {t.rich("haveAccount", {
              login: (chunks) => (
                <Link href="/login" className="py-3 font-semibold text-ink underline decoration-1 hover:decoration-2">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </div>
        <HeroComposition />
      </div>
      <Stats />
      <Lattice />
    </section>
  );
}
