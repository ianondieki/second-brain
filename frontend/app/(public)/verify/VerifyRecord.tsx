import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon } from "@/components/ui/icons";

import { formatKenyan, KEYS_HREF, NAIROBI, tokenHref, type CertificateCheck } from "./certificate";
import { Fingerprint } from "./Fingerprint";

/**
 * One certificate as the public sees it (docs/spec/06 6.4 item 2): status, fingerprint, timestamp, TSA serial, key id
 * and signature, and nothing that names the owner or the proposal (D-33 default: no name or title). The status is
 * icon + words + colour; the API's own status label is not shown, so the wording can be translated.
 */
export function VerifyRecord({ record }: { record: CertificateCheck }) {
  const t = useTranslations("verify");
  const locale = useLocale();
  const done = record.status === "timestamped";
  const when = record.timestamp ? new Date(record.timestamp) : null;

  return (
    <div>
      <p className={cn("flex items-start gap-2 text-lg font-semibold", done ? "text-ok" : "text-jacaranda")}>
        {done ? <CheckIcon className="mt-1 size-5 shrink-0" /> : <InfoIcon className="mt-1 size-5 shrink-0" />}
        <span data-testid="verify-status">{done ? t("statusTimestamped") : t("statusPending")}</span>
      </p>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{done ? t("explainTimestamped") : t("explainPending")}</p>

      {/* The record itself hangs off one jacaranda stroke: the bridge line, as on the certificate. */}
      <div className="mt-8 border-l-4 border-jacaranda pl-4 sm:pl-6">
        <h2 className="text-sm font-medium text-ink-soft">{t("hash")}</h2>
        <Fingerprint hex={record.content_hash} className="mt-1" />

        <dl className="mt-6 grid gap-x-8 gap-y-4 sm:grid-cols-[minmax(10rem,auto)_1fr]">
          <Row label={t("time")}>
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
          </Row>
          <Row label={t("serial")}>
            {record.tsa_serial ? <Code>{record.tsa_serial}</Code> : <NotYet label={t("notYet")} />}
          </Row>
          <Row label={t("key")}>{record.key_id ? <Code>{record.key_id}</Code> : <NotYet label={t("notYet")} />}</Row>
          <Row label={t("signature")}>
            {record.signature ? (
              <Code className="text-sm text-ink-soft">{record.signature}</Code>
            ) : (
              <NotYet label={t("notYet")} />
            )}
          </Row>
        </dl>

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
      </div>

      <p className="mt-8 max-w-[62ch] text-sm text-ink-soft">{t("evidence")}</p>
      <p className="mt-2 max-w-[62ch] text-sm text-ink-soft">{t("private")}</p>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm font-medium text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Code({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("code-figures block break-all text-ink", className)}>{children}</span>;
}

function NotYet({ label }: { label: string }) {
  return <span className="text-ink-soft italic">{label}</span>;
}
