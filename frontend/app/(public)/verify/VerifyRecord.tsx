import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Seal } from "@/components/brand/Seal";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Lattice } from "@/components/ui/Lattice";
import { Section } from "@/components/ui/Section";
import { CheckIcon, ClockIcon } from "@/components/ui/status-icons";

import { formatMomentSeconds } from "@/lib/format";

import { KEYS_HREF, NAIROBI, tokenHref, type CertificateCheck } from "./certificate";
import { Fingerprint } from "./Fingerprint";

/**
 * One certificate as the public sees it (docs/spec/06 6.4 item 2): status, fingerprint, timestamp, TSA serial, key id
 * and signature, and nothing that names the owner or the proposal (D-33 default: no name or title). It is a sheet
 * like the owner's certificate (D-52): the lattice edge, the seal, the status as icon + words + tone (warm check
 * when timestamped, clock in the accent while pending; the API's own label is not shown, so the wording can be
 * translated), then the fingerprint and the record's facts as a DescriptionList.
 */
export function VerifyRecord({ record }: { record: CertificateCheck }) {
  const t = useTranslations("verify");
  const locale = useLocale();
  const done = record.status === "timestamped";
  const at = record.timestamp;

  return (
    <div>
      <Card as="article" padding="none" data-verify-record={record.cert_id} className="overflow-hidden">
        <Lattice />
        <div className="p-5 sm:p-8">
          {/* The answer first: icon + words + tone, with the seal beside it from 640 px. */}
          <div className="flex items-start justify-between gap-6">
            <div className="flex min-w-0 items-start gap-3">
              <span
                aria-hidden="true"
                className={cn(
                  "mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-full",
                  done ? "bg-warm-wash text-warm" : "bg-accent-wash text-accent",
                )}
              >
                {done ? <CheckIcon className="size-5" /> : <ClockIcon className="size-5" />}
              </span>
              <div className="min-w-0">
                <p className="text-lg font-semibold text-ink">
                  <span data-testid="verify-status">{done ? t("statusTimestamped") : t("statusPending")}</span>
                </p>
                <p className="mt-1 max-w-[62ch] text-ink-soft">{done ? t("explainTimestamped") : t("explainPending")}</p>
              </div>
            </div>
            <Seal size={96} className="hidden sm:block" />
          </div>

          <Section title={t("hash")} className="mt-8">
        <Fingerprint hex={record.content_hash} />

        <DescriptionList figures className="mt-6">
          <Description label={t("time")}>
            {at ? (
              <>
                <time dateTime={at} className="block text-ink">
                  {t("timeEat", {
                    time: formatMomentSeconds(locale, at, NAIROBI),
                  })}
                </time>
                <span className="block text-sm text-ink-soft">
                  {t("timeUtc", {
                    time: formatMomentSeconds(locale, at, "UTC"),
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
        </div>
      </Card>

      <p className="mt-6 max-w-[62ch] text-sm text-ink-soft">{t("evidence")}</p>
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
