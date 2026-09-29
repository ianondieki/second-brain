import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { IntlScope } from "@/components/IntlScope";
import { buttonClass } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";

import { normaliseCertId } from "./certificate";
import { FileCheck } from "./FileCheck";
import { VerifyShell } from "./VerifyShell";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("verify");
  return { title: t("pageTitle") };
}

/**
 * Public /verify (REQ-PROV-02, F3): look up a certificate by id, or check a file against every registered record.
 * The lookup is a plain GET form, so it works before (or without) JavaScript: /verify?id=… redirects to
 * /verify/{id} when the id is well formed, and shows the field error otherwise.
 */
export default async function VerifyPage({ searchParams }: PageProps<"/verify">) {
  const t = await getTranslations("verify");
  const raw = (await searchParams).id;
  const typed = typeof raw === "string" ? raw : undefined;
  if (typed !== undefined) {
    const certId = normaliseCertId(typed);
    if (certId) redirect(`/verify/${certId}`);
  }
  const invalid = typed !== undefined;

  return (
    <VerifyShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-3 max-w-[62ch] text-ink-soft">{t("lead")}</p>
      <form method="get" action="/verify" noValidate className="mt-6 flex max-w-md flex-col gap-5">
        <TextField
          id="cert-id"
          name="id"
          label={t("idLabel")}
          hint={t("idHint")}
          error={invalid ? t("idInvalid") : undefined}
          defaultValue={typed?.slice(0, 64)}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          maxLength={64}
          className="code-figures"
          autoFocus={invalid}
        />
        <div>
          <button type="submit" data-primary="" className={buttonClass("primary")}>
            {t("submit")}
          </button>
        </div>
      </form>

      <div className="mt-12 border-t border-line pt-8">
        <IntlScope namespaces={["verifyFile"]}>
          <FileCheck />
        </IntlScope>
      </div>
    </VerifyShell>
  );
}
