import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { ButtonLink } from "@/components/ui/ButtonLink";
import { Lattice } from "@/components/ui/Lattice";

import { HeroComposition } from "./HeroComposition";

/**
 * The hero on the night band (D-55): the promise set large in the display face, the lead, the one primary action
 * (saffron on night) and a quieter way to check a certificate, then the product's own parts beside it. The band ends
 * on the kanga lattice. The text column takes the night tokens (.on-night); the product cards keep the page's own.
 */
export async function Hero() {
  const t = await getTranslations("landing");
  return (
    <section aria-labelledby="hero-title" className="relative isolate overflow-hidden bg-night">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-14 px-4 pt-14 pb-20 sm:px-6 sm:pt-20 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] xl:items-center xl:gap-12 lg:pt-24 lg:pb-28">
        <div className="on-night">
          <h1
            id="hero-title"
            className="max-w-[15ch] text-[2.75rem] text-balance leading-[1] tracking-[-0.035em] sm:text-4xl lg:text-[4.25rem] lg:leading-[0.98] xl:text-[4rem]"
          >
            {t("title")}
          </h1>
          <p className="mt-7 max-w-[50ch] text-lg text-ink-soft">{t("lead")}</p>
          <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
            <ButtonLink
              href="/signup"
              variant="primary"
              className="bg-flourish text-night shadow-[0_10px_28px_-12px_rgb(244_181_63/0.65)] hover:bg-flourish hover:brightness-105"
            >
              {t("signUp")}
            </ButtonLink>
            <ButtonLink href="/verify" variant="secondary" className="border-line bg-transparent text-ink hover:bg-accent-wash">
              {t("hero.check")}
            </ButtonLink>
          </div>
          <p className="mt-7 text-ink-soft">
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
      <Lattice className="absolute inset-x-0 bottom-0" />
    </section>
  );
}
