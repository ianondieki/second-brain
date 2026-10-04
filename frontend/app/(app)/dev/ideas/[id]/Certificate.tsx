import { getTranslations } from "next-intl/server";

import { CertificateSheet } from "@/components/certificate/CertificateSheet";
import { PrintButton } from "@/components/certificate/PrintButton";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import type { MyProposal } from "../ideas";

/**
 * The public verify address printed on the sheet and encoded in its QR: NEXT_PUBLIC_SITE_ORIGIN (frontend/.env.example)
 * plus the path; with no origin configured, the path alone (never the server's own host or localhost).
 */
export function verifyAddress(certId: string, origin: string | undefined = process.env.NEXT_PUBLIC_SITE_ORIGIN): string {
  const path = `/verify/${encodeURIComponent(certId)}`;
  const base = origin?.trim().replace(/\/+$/, "");
  return base ? `${base}${path}` : path;
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
    <Section title={t("certificateTitle")} headingId="certificate-heading" description={t("certificateLead")}>
      {current && certId ? (
        <>
          <CertificateSheet
            title={current.teaser.title?.trim() || t("untitled")}
            ownerName={ownerName}
            versionNo={current.version_no}
            certId={certId}
            registeredAt={current.registered_at}
            stamped={stamped}
            verifyUrl={verifyAddress(certId)}
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
