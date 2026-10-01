import { headers } from "next/headers";
import { getTranslations } from "next-intl/server";

import { CertificateSheet } from "@/components/certificate/CertificateSheet";
import { PrintButton } from "@/components/certificate/PrintButton";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import type { MyProposal } from "../ideas";

/** This site's origin as the request names it (behind the edge proxy: the forwarded values), for the QR's absolute link. */
async function siteOrigin(): Promise<string> {
  let host = "localhost:3000";
  let proto: string | null = null;
  try {
    const h = await headers();
    host = h.get("x-forwarded-host") ?? h.get("host") ?? host;
    proto = h.get("x-forwarded-proto");
  } catch {
    // Outside a request (a unit test of the page's reads): the local address.
  }
  proto ??= host.startsWith("localhost") || host.startsWith("127.") ? "http" : "https";
  return `${proto}://${host}`;
}

/**
 * The authorship certificate of an idea's page (REQ-PROV-01; D-52): the sheet as the default view, then its links
 * (the public record, the PDF once timestamped) and Print.
 */
export async function Certificate({ idea, ownerName }: { idea: MyProposal; ownerName: string }) {
  const t = await getTranslations("ideas");
  const current = idea.current;
  const certId = current?.cert_id;
  const stamped = current?.provenance?.status === "timestamped";
  return (
    <Section title={t("certificateTitle")} headingId="certificate-heading" description={t("certificateLead")} className="mt-10">
      {current && certId ? (
        <>
          <CertificateSheet
            title={current.teaser.title?.trim() || t("untitled")}
            ownerName={ownerName}
            versionNo={current.version_no}
            certId={certId}
            registeredAt={current.registered_at}
            stamped={stamped}
            verifyUrl={`${await siteOrigin()}/verify/${encodeURIComponent(certId)}`}
            animate
          />
          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2" data-no-print="">
            <StandaloneLink href={`/verify/${encodeURIComponent(certId)}`}>{t("verifyLink")}</StandaloneLink>
            {stamped ? (
              // A plain link: the API answers with the PDF as an attachment (generated on demand, never stored).
              <a href={`/api/provenance/certificates/${encodeURIComponent(certId)}/certificate.pdf`} download className={standaloneLinkClass}>
                {t("download")}
              </a>
            ) : (
              <p className="py-2.5 text-ink-soft">{t("downloadLater")}</p>
            )}
            <PrintButton label={t("sheet.print")} />
          </div>
        </>
      ) : (
        <p className="text-ink-soft">{t("noCertificate")}</p>
      )}
    </Section>
  );
}
