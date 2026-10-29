import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

import type { ReadRefusal } from "./data";

/** An engagement the caller cannot open: one sentence and one way on (docs/spec/07 item 4). */
export async function Refused({ refusal, backHref }: { refusal: ReadRefusal; backHref: string }) {
  const t = await getTranslations("tracker");
  return (
    <>
      <PageHeader title={t("title")} />
      <EmptyState
        className="mt-6"
        data-refusal={refusal}
        sentence={t(`refused.${refusal}`)}
        action={refusal === "mfaSetup" ? t("turnOnMfa") : t("back")}
        href={refusal === "mfaSetup" ? "/settings/security" : backHref}
      />
    </>
  );
}
