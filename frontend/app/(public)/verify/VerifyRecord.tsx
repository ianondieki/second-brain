import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Wordmark } from "@/components/brand/Logo";
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
 * and signature, and nothing that names the owner or the proposal (D-33 default: no name or title). It is an official
 * sheet like the owner's certificate (D-52, P20): framed top and foot by the lattice (the kanga border), the
 * wordmark and the seal as its masthead, the status as icon + words + tone in the display face (warm check when
 * timestamped, clock in the accent while pending; the API's own label is not shown, so the wording can be
 * translated), the fingerprint in its own well, the record's facts as a DescriptionList, and the token and keys
 * links in the sheet's foot.
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
          {/* The masthead: whose register this is and its seal, then the answer as icon + words + tone. */}
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-4">
                <Wordmark size={22} />
                <Seal size={56} className="sm:hidden" />
              </div>
              <div className="mt-4 flex items-center gap-3 sm:mt-6">
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-10 shrink-0 items-center justify-center rounded-full",
                    done ? "bg-warm-wash text-warm" : "bg-accent-wash text-accent",
                  )}
                >
                  {done ? <CheckIcon className="size-5" /> : <ClockIcon className="size-5" />}
                </span>
                <p className="font-display text-xl leading-tight font-[680] tracking-[-0.02em] text-ink sm:text-2xl">
                  <span data-testid="verify-status">{done ? t("statusTimestamped") : t("statusPending")}</span>
                </p>
              </div>
              <p className="mt-3 max-w-[56ch] text-ink-soft">{done ? t("explainTimestamped") : t("explainPending")}</p>
            </div>
            <Seal size={112} className="hidden sm:block" />
          </div>

          <Section title={t("hash")} className="mt-8 border-t border-line pt-6">
            {/* The fingerprint in its own well, the one thing a reader compares by eye. */}
            <div className="rounded-control border border-line bg-paper px-4 py-3">
              <Fingerprint hex={record.content_hash} />
            </div>

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
          </Section>
        </div>

        {/* The sheet's foot: where the evidence can be taken away and checked independently. */}
        <ul
          className="flex flex-col items-start border-t border-line bg-accent-wash px-5 py-2 sm:flex-row sm:flex-wrap sm:gap-x-8 sm:px-8"
          data-testid="record-links"
        >
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
        <Lattice />
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
