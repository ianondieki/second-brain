import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { IntlScope } from "@/components/IntlScope";
import { standaloneLinkClass } from "@/components/ui/Button";

import { normaliseCertId } from "../certificate";
import { FileCheck } from "../FileCheck";
import { lookupCertificate } from "../lookup";
import { VerifyShell } from "../VerifyShell";
import { VerifyRecord } from "../VerifyRecord";

/** The path segment as typed; a stray "%" that does not decode is kept as is (it then fails the id pattern). */
function segment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

// Certificate pages are for people holding a certificate, not for search engines.
const NOT_INDEXED: Metadata["robots"] = { index: false, follow: false };

export async function generateMetadata({ params }: PageProps<"/verify/[certId]">): Promise<Metadata> {
  const t = await getTranslations("verify");
  const certId = normaliseCertId(segment((await params).certId));
  return { title: certId ? t("recordTitle", { certId }) : t("pageTitle"), robots: NOT_INDEXED };
}

/**
 * Public /verify/{cert_id} (REQ-PROV-02, F3; the QR code on a certificate points here): the record from
 * GET /api/verify/{cert_id}, rendered on the server, then "Check a file" against this certificate. An id typed with
 * spaces or in lower case redirects to its canonical form; one that cannot be an id is "not found" with no request.
 */
export default async function CertificatePage({ params }: PageProps<"/verify/[certId]">) {
  const t = await getTranslations("verify");
  const typed = segment((await params).certId);
  const certId = normaliseCertId(typed);
  if (certId && certId !== typed) redirect(`/verify/${certId}`);
  const lookup = certId ? await lookupCertificate(certId) : ({ kind: "notFound" } as const);

  if (lookup.kind !== "found" || !certId) {
    // One sentence and one action (docs/spec/07 item 4).
    const again = lookup.kind === "rateLimited" || lookup.kind === "unavailable";
    return (
      <VerifyShell>
        <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
        <p className="mt-3 text-ink" data-testid="verify-message">
          {lookup.kind === "rateLimited"
            ? t("rateLimited")
            : lookup.kind === "unavailable"
              ? t("unavailable")
              : t("notFound")}
        </p>
        <div className="mt-6">
          {again && certId ? (
            <Link href={`/verify/${certId}`} className={standaloneLinkClass}>
              {t("retry")}
            </Link>
          ) : (
            <Link href="/verify" className={standaloneLinkClass}>
              {t("another")}
            </Link>
          )}
        </div>
      </VerifyShell>
    );
  }

  return (
    <VerifyShell>
      <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">{t("recordTitle", { certId })}</h1>
      <div className="mt-4">
        <VerifyRecord record={lookup.record} />
      </div>
      <div className="mt-12 border-t border-line pt-8">
        <IntlScope namespaces={["verifyFile"]}>
          <FileCheck certId={certId} primary />
        </IntlScope>
      </div>
      <p className="mt-10">
        <Link href="/verify" className={standaloneLinkClass}>
          {t("another")}
        </Link>
      </p>
    </VerifyShell>
  );
}
