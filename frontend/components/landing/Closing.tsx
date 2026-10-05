import { getTranslations } from "next-intl/server";

import { ButtonLink } from "@/components/ui/ButtonLink";
import { Lattice } from "@/components/ui/Lattice";

/** The closing call (D-55): one bloom panel with the lattice for its edge; its button is secondary (the hero holds the one primary). */
export async function Closing() {
  const t = await getTranslations("landing.cta");
  return (
    <section aria-labelledby="cta-title" className="px-4 pb-20 sm:px-6 lg:pb-28">
      <div className="mx-auto w-full max-w-6xl overflow-hidden rounded-[2rem] bg-accent">
        <Lattice />
        <div className="flex flex-col gap-8 px-6 py-12 sm:px-12 lg:flex-row lg:items-end lg:justify-between lg:py-16">
          <div>
            <h2 id="cta-title" className="text-3xl text-on-accent lg:text-4xl">
              {t("title")}
            </h2>
            <p className="mt-3 max-w-[48ch] text-lg text-on-accent">{t("lead")}</p>
          </div>
          <ButtonLink href="/signup" variant="secondary" className="shrink-0 border-transparent px-7">
            {t("action")}
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
