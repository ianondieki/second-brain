import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Picture } from "@/components/landing/Picture";
import { PublicFrame } from "@/components/landing/PublicFrame";
import { CREDITED } from "@/lib/photos/photos";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("credits");
  return { title: t("pageTitle") };
}

/**
 * Credits (D-66): every photograph on the site with its attribution line as its licence asks (public/photos/CREDITS.md
 * holds the full record), and the typefaces with their licence. Server-rendered text only.
 */
export default async function CreditsPage() {
  const t = await getTranslations("credits");
  return (
    <PublicFrame>
      <div className="mx-auto w-full max-w-3xl px-4 pt-10 pb-20 sm:px-6 lg:pt-16 lg:pb-28">
        <h1 className="text-[2.5rem] leading-[1.05] text-ink lg:text-[3.25rem]">{t("title")}</h1>
        <p className="mt-4 max-w-[60ch] text-lg text-ink-soft">{t("lead")}</p>
        <section aria-labelledby="credits-photos" className="mt-12">
          <h2 id="credits-photos" className="text-2xl text-ink">
            {t("photos")}
          </h2>
          <ul className="mt-4 flex flex-col divide-y divide-line border-y border-line" data-credits="photos">
            {CREDITED.map((photo) => (
              <li key={photo.slug} className="grid grid-cols-[5rem_minmax(0,1fr)] items-center gap-4 py-4 sm:grid-cols-[7rem_minmax(0,1fr)]">
                <Picture photo={photo} sizes="7rem" className="aspect-[4/3] w-full rounded-lg object-cover" />
                <div>
                  <p className="font-semibold text-ink">{photo.caption}</p>
                  <p className="mt-1 text-sm text-ink-soft [overflow-wrap:anywhere]">{photo.credit}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="credits-fonts" className="mt-12">
          <h2 id="credits-fonts" className="text-2xl text-ink">
            {t("fonts")}
          </h2>
          <p className="mt-4 text-ink-soft">{t("fontsBody")}</p>
        </section>
      </div>
    </PublicFrame>
  );
}
