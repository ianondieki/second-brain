import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { TopBar } from "@/components/TopBar";
import { PageHeader } from "@/components/ui/PageHeader";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal");
  return { title: t("termsTitle") };
}

/**
 * The terms of service as a reading page (P20): the top bar, then one column at a comfortable measure (about 68
 * characters), not the sign-in shell, so a long text reads like a document. Placeholder until the advocate-reviewed
 * terms arrive at G2 (GATES.md); agents never write legal text. When they arrive, a contents list goes beside the
 * column as on Help.
 */
export default async function TermsPage() {
  const t = await getTranslations("legal");
  return (
    <>
      <TopBar />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16">
        <article aria-labelledby="terms-title" className="max-w-[68ch]">
          <PageHeader titleId="terms-title" title={t("termsTitle")} />
          <div className="mt-8 border-t border-line pt-8 text-ink">
            <p>{t("termsBody")}</p>
          </div>
        </article>
      </main>
    </>
  );
}
