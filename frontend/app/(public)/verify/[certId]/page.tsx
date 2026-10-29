import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { IntlScope } from "@/components/IntlScope";
import { standaloneLinkClass } from "@/components/ui/Button";
import { EmptyStateFrame } from "@/components/ui/EmptyStateFrame";
import { PageHeader } from "@/components/ui/PageHeader";

import { normaliseCertId } from "../certificate";
import { FileCheck } from "../FileCheck";
import { lookupCertificate } from "../lookup";
import { VerifyShell } from "../VerifyShell";
import { VerifyRecord } from "../VerifyRecord";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

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
  const [t, tOg] = await Promise.all([getTranslations("verify"), getTranslations("og")]);
  const certId = normaliseCertId(segment((await params).certId));
  return {
    title: certId ? t("recordTitle", { certId }) : t("pageTitle"),
    robots: NOT_INDEXED,
    // The share card (P24, app/og/verify): the id and "Registered on Wazo"; it answers 404 for an unknown id.
    openGraph: certId ? { images: [{ url: `/og/verify/${certId}`, width: 1200, height: 630, alt: tOg("verifyAlt", { certId }) }] } : undefined,
  };
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
        <PageHeader title={t("pageTitle")} />
        <EmptyStateFrame
          rule={false}
          className="mt-6"
          sentence={
            <span data-testid="verify-message">
              {lookup.kind === "rateLimited" ? t("rateLimited") : lookup.kind === "unavailable" ? t("unavailable") : t("notFound")}
            </span>
          }
          action={
            again && certId ? (
              <StandaloneLink href={`/verify/${certId}`}>{t("retry")}</StandaloneLink>
            ) : (
              <Link href="/verify" className={standaloneLinkClass}>
                {t("another")}
              </Link>
            )
          }
        />
      </VerifyShell>
    );
  }

  return (
    <VerifyShell>
      <PageHeader title={t("recordTitle", { certId })} />
      <div className="mt-6">
        <VerifyRecord record={lookup.record} />
      </div>
      <div className="mt-8">
        <IntlScope namespaces={["verifyFile"]}>
          <FileCheck certId={certId} primary />
        </IntlScope>
      </div>
      <p className="mt-8">
        <Link href="/verify" className={standaloneLinkClass}>
          {t("another")}
        </Link>
      </p>
    </VerifyShell>
  );
}
