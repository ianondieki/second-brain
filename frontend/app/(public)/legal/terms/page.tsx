import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PublicFrame } from "@/components/landing/PublicFrame";
import { PageHeader } from "@/components/ui/PageHeader";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal");
  return { title: t("termsTitle") };
}

/**
 * The terms of service as a reading page (P20; the landing's public frame, D-67): the top bar and footer, then one column at a comfortable measure (about 68
 * characters), not the sign-in shell, so a long text reads like a document. Placeholder until the advocate-reviewed
 * terms arrive at G2 (GATES.md); agents never write legal text. When they arrive, a contents list goes beside the
 * column as on Help.
 */
export default async function TermsPage() {
  const [t, tp] = await Promise.all([getTranslations("legal"), getTranslations("portal")]);
  return (
    <PublicFrame>
      <div className="mx-auto w-full max-w-6xl px-4 pt-8 pb-16 sm:px-6 lg:pt-16">
        <article aria-labelledby="terms-title" className="max-w-[68ch]">
          <p className="page-eyebrow mb-3" data-eyebrow="">
            {tp("eyebrow.legal")}
          </p>
          <PageHeader titleId="terms-title" title={t("termsTitle")} className="[&_h1]:text-[2rem] lg:[&_h1]:text-[2.75rem]" />
          <div className="mt-8 border-t border-line pt-8 text-ink">
            <p>{t("termsBody")}</p>
          </div>
        </article>
      </div>
    </PublicFrame>
  );
}
