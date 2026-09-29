import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass } from "@/components/ui/Button";

import type { ReadRefusal } from "./data";

/** An engagement the caller cannot open: one sentence and one way on (docs/spec/07 item 4). */
export async function Refused({ refusal, backHref }: { refusal: ReadRefusal; backHref: string }) {
  const t = await getTranslations("tracker");
  return (
    <>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <div data-empty-state="" data-refusal={refusal} className="mt-6 flex flex-col items-start gap-3 border-t border-line pt-6">
        <p className="max-w-[60ch] text-ink">{t(`refused.${refusal}`)}</p>
        {refusal === "mfaSetup" ? (
          <Link href="/settings/security" className={standaloneLinkClass}>
            {t("turnOnMfa")}
          </Link>
        ) : (
          <Link href={backHref} className={standaloneLinkClass}>
            {t("back")}
          </Link>
        )}
      </div>
    </>
  );
}
