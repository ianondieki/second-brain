import { getLocale, getTranslations } from "next-intl/server";
import { encode } from "uqr";

import { Seal } from "@/components/brand/Seal";
import { Wordmark } from "@/components/brand/Logo";
import { QrCode } from "@/components/QrCode";
import { Badge } from "@/components/ui/Badge";
import { Lattice } from "@/components/ui/Lattice";
import { CheckIcon, ClockIcon } from "@/components/ui/status-icons";
import { formatMoment } from "@/lib/format";

import { Fingerprint } from "@/app/(public)/verify/Fingerprint";

export interface CertificateSheetProps {
  title: string;
  ownerName: string;
  versionNo: number;
  certId: string;
  registeredAt: string | null;
  stamped: boolean;
  /** The public verify address as the sheet prints it and the QR encodes it: absolute when a public origin is configured, else the path. */
  verifyUrl: string;
  /** The version's SHA-256, when the caller has it (the public record does; the owner's idea page does not yet). */
  fingerprint?: string | null;
  /** The seal's ring draws once on the owner's page; still everywhere else. */
  animate?: boolean;
}

/**
 * The authorship certificate as a sheet (D-52, the showpiece): the lattice edge, the seal, the idea and its author,
 * the certificate id, the registration time, the evidence status, the fingerprint when known, and a QR to the public
 * verify page. Printable: `data-print-sheet` keeps it alone on paper (app/globals.css).
 */
export async function CertificateSheet({ title, ownerName, versionNo, certId, registeredAt, stamped, verifyUrl, fingerprint, animate = false }: CertificateSheetProps) {
  const t = await getTranslations("ideas.sheet");
  const locale = await getLocale();
  const qr = encode(verifyUrl, { ecc: "M" }).data;
  return (
    <article data-print-sheet="" data-certificate={certId} className="overflow-hidden rounded-panel border border-line bg-field shadow-card">
      <Lattice />
      <div className="p-6 sm:p-8">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <Wordmark size={22} />
            <p className="mt-4 text-sm font-medium text-ink-soft">{t("title")}</p>
            <h3 className="mt-1 font-display text-xl font-medium text-ink [overflow-wrap:anywhere]">{title}</h3>
            <p className="mt-1 text-ink-soft">{t("registeredBy", { name: ownerName, number: versionNo })}</p>
          </div>
          <Seal size={104} animate={animate} className="hidden sm:block" />
        </div>
        <dl className="mt-6 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="text-ink-soft">{t("certificate")}</dt>
          <dd className="font-semibold tracking-[0.06em] text-ink tabular-nums [overflow-wrap:anywhere]">{certId}</dd>
          {registeredAt ? (
            <>
              <dt className="text-ink-soft">{t("registered")}</dt>
              <dd className="text-ink tabular-nums">{formatMoment(locale, registeredAt)}</dd>
            </>
          ) : null}
          <dt className="text-ink-soft">{t("evidence")}</dt>
          <dd>
            <Badge tone={stamped ? "ok" : "neutral"} icon={stamped ? <CheckIcon /> : <ClockIcon />}>
              {stamped ? t("timestamped") : t("pending")}
            </Badge>
          </dd>
          {fingerprint ? (
            <>
              <dt className="text-ink-soft">SHA-256</dt>
              <dd>
                <Fingerprint hex={fingerprint} className="text-sm leading-6" />
              </dd>
            </>
          ) : null}
        </dl>
      </div>
      <div className="flex items-center justify-between gap-4 border-t border-line bg-accent-wash px-6 py-4 sm:px-8">
        <p className="text-sm text-ink [overflow-wrap:anywhere]">{t("checkAt", { url: verifyUrl })}</p>
        <div className="flex shrink-0 flex-col items-center gap-1">
          <QrCode matrix={qr} label={t("qrLabel", { id: certId })} className="size-24 rounded-[4px]" />
          <span className="text-xs text-ink-soft">{t("scan")}</span>
        </div>
      </div>
    </article>
  );
}
