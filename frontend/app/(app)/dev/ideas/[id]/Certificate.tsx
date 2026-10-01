import { getLocale, getTranslations } from "next-intl/server";

import { Badge } from "@/components/ui/Badge";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { CheckIcon, ClockIcon } from "@/components/ui/icons";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import { formatMoment } from "../dates";
import type { MyProposal } from "../ideas";

/** The authorship certificate section of an idea's page (REQ-PROV-01): id, registration time, evidence status, links. */
export async function Certificate({ idea }: { idea: MyProposal }) {
  const t = await getTranslations("ideas");
  const locale = await getLocale();
  const current = idea.current;
  const certId = current?.cert_id;
  const stamped = current?.provenance?.status === "timestamped";
  return (
    <Section title={t("certificateTitle")} headingId="certificate-heading" description={t("certificateLead")} className="mt-12">
      {current && certId ? (
        <>
          <DescriptionList figures>
            <Description label={t("certificateId")}>
              <span className="font-semibold tracking-[0.06em] tabular-nums [overflow-wrap:anywhere]">{certId}</span>
            </Description>
            {current.registered_at ? (
              <Description label={t("registered")}>
                {t("registeredAt", { time: formatMoment(locale, current.registered_at) })}
              </Description>
            ) : null}
            <Description label={t("evidenceStatus")}>
              <Badge tone={stamped ? "ok" : "neutral"} icon={stamped ? <CheckIcon /> : <ClockIcon />}>
                {stamped ? t("timestamped") : t("timestampPending")}
              </Badge>
            </Description>
          </DescriptionList>
          <ul className="mt-4 flex flex-col">
            <li>
              <StandaloneLink href={`/verify/${encodeURIComponent(certId)}`}>
                {t("verifyLink")}
              </StandaloneLink>
            </li>
            <li>
              {stamped ? (
                // A plain link: the API answers with the PDF as an attachment (generated on demand, never stored).
                <a
                  href={`/api/provenance/certificates/${encodeURIComponent(certId)}/certificate.pdf`}
                  download
                  className={standaloneLinkClass}
                >
                  {t("download")}
                </a>
              ) : (
                <p className="py-2.5 text-ink-soft">{t("downloadLater")}</p>
              )}
            </li>
          </ul>
        </>
      ) : (
        <p className="text-ink-soft">{t("noCertificate")}</p>
      )}
    </Section>
  );
}
