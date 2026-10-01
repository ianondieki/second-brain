import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Seal } from "@/components/brand/Seal";
import { IntlScope } from "@/components/IntlScope";
import { buttonClass, primaryMark } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Lattice } from "@/components/ui/Lattice";
import { PageHeader } from "@/components/ui/PageHeader";
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
export default async function VerifyPage({
  searchParams,
}: PageProps<"/verify">) {
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
      <PageHeader title={t("title")} lead={t("lead")} />
      <Card padding="none" className="mt-8 overflow-hidden">
        <Lattice />
        <div className="flex items-start justify-between gap-8 p-5 sm:p-8">
          <form
            method="get"
            action="/verify"
            noValidate
            className="flex w-full max-w-md flex-col gap-5"
          >
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
              {/* A plain GET form on a server page: the Button component's click handler cannot cross to the browser. */}
              <button
                type="submit"
                className={buttonClass("primary")}
                {...primaryMark("primary")}
              >
                {t("submit")}
              </button>
            </div>
          </form>
          <Seal size={96} className="hidden sm:block" />
        </div>
      </Card>

      <div className="mt-8">
        <IntlScope namespaces={["verifyFile"]}>
          <FileCheck />
        </IntlScope>
      </div>
    </VerifyShell>
  );
}
