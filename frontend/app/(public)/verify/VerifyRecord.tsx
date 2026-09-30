import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Section } from "@/components/ui/Section";

import { formatKenyan, KEYS_HREF, NAIROBI, tokenHref, type CertificateCheck } from "./certificate";
import { Fingerprint } from "./Fingerprint";

/**
 * One certificate as the public sees it (docs/spec/06 6.4 item 2): status, fingerprint, timestamp, TSA serial, key id
 * and signature, and nothing that names the owner or the proposal (D-33 default: no name or title). The status is
 * icon + words + tone (a Callout); the API's own status label is not shown, so the wording can be translated. The
 * record's facts are a DescriptionList under the fingerprint's Section.
 */
export function VerifyRecord({ record }: { record: CertificateCheck }) {
  const t = useTranslations("verify");
  const locale = useLocale();
  const done = record.status === "timestamped";
  const when = record.timestamp ? new Date(record.timestamp) : null;

  return (
    <div>
      {/* The answer first, as the system's notice: icon + words + tone (ok when timestamped, info while pending). */}
      <Callout
        tone={done ? "ok" : "info"}
        titleSize="lg"
        title={<span data-testid="verify-status">{done ? t("statusTimestamped") : t("statusPending")}</span>}
      >
        <p className="max-w-[62ch] text-ink-soft">{done ? t("explainTimestamped") : t("explainPending")}</p>
      </Callout>

      <Section title={t("hash")} className="mt-10">
        <Fingerprint hex={record.content_hash} />

        <DescriptionList figures className="mt-6">
          <Description label={t("time")}>
            {when ? (
              <>
                <time dateTime={record.timestamp ?? undefined} className="block text-ink">
                  {t("timeEat", {
                    time: formatKenyan(locale, when, { dateStyle: "long", timeStyle: "medium", timeZone: NAIROBI }),
                  })}
                </time>
                <span className="block text-sm text-ink-soft">
                  {t("timeUtc", {
                    time: formatKenyan(locale, when, { dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" }),
                  })}
                </span>
              </>
            ) : (
              <NotYet label={t("notYet")} />
            )}
          </Description>
          <Description label={t("serial")}>
            {record.tsa_serial ? <Code>{record.tsa_serial}</Code> : <NotYet label={t("notYet")} />}
          </Description>
          <Description label={t("key")}>
            {record.key_id ? <Code>{record.key_id}</Code> : <NotYet label={t("notYet")} />}
          </Description>
          <Description label={t("signature")}>
            {record.signature ? (
              <Code className="text-sm text-ink-soft">{record.signature}</Code>
            ) : (
              <NotYet label={t("notYet")} />
            )}
          </Description>
        </DescriptionList>

        <ul className="mt-4 flex flex-col items-start" data-testid="record-links">
          {done ? (
            <li>
              <a href={tokenHref(record.cert_id)} download className={standaloneLinkClass}>
                {t("token")}
              </a>
            </li>
          ) : null}
          <li>
            <a href={KEYS_HREF} className={standaloneLinkClass}>
              {t("keys")}
            </a>
          </li>
        </ul>
      </Section>

      <p className="mt-10 max-w-[62ch] text-sm text-ink-soft">{t("evidence")}</p>
      <p className="mt-2 max-w-[62ch] text-sm text-ink-soft">{t("private")}</p>
    </div>
  );
}

function Code({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("code-figures block break-all text-ink", className)}>{children}</span>;
}

function NotYet({ label }: { label: string }) {
  return <span className="text-ink-soft italic">{label}</span>;
}
