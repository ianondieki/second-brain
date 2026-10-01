import { getLocale, getTranslations } from "next-intl/server";
import { encode } from "uqr";

import { DevNav } from "@/components/DevNav";
import { QrCode } from "@/components/QrCode";
import { SignedInShell } from "@/components/SignedInShell";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { CheckIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";

import { Certificate } from "@/app/(app)/dev/ideas/[id]/Certificate";
import { formatMoment } from "@/app/(app)/dev/ideas/dates";
import { IdeaStatusBadge } from "@/app/(app)/dev/ideas/IdeaStatusBadge";
import { Fingerprint } from "@/app/(public)/verify/Fingerprint";

import { LogoMark } from "../brand/Logo";
import type { DirectionKey } from "../directions";
import { CERT_ID, IDEA, PLACEHOLDER_NAME, SHA256 } from "../fixtures";

/**
 * The idea page's header and its real Certificate section, then the lab's preview of the step-3 showpiece: a
 * certificate sheet with the seal (the direction's mark), the registration time, the fingerprint and a QR to /verify.
 */
export async function CertificateScreen({ direction }: { direction: DirectionKey }) {
  const t = await getTranslations("ideas");
  const locale = await getLocale();
  const qr = encode(`https://example.test/verify/${CERT_ID}`, { ecc: "M" }).data;
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="ideas" />}>
      <PageHeader back={{ href: "/dev/ideas", label: t("back") }} title={IDEA.current!.teaser.title!}>
        <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
          <IdeaStatusBadge status="published" />
          <span className="text-sm text-ink-soft">{t("version", { number: 2 })}</span>
        </p>
      </PageHeader>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <ButtonLink href="#" variant="primary">
          Pitch to companies
        </ButtonLink>
        <ButtonLink href="#" variant="secondary">
          {t("edit")}
        </ButtonLink>
      </div>

      <Certificate idea={IDEA} />

      <section aria-labelledby="sheet-heading" className="mt-12">
        <h2 id="sheet-heading" className="text-lg text-ink">
          Certificate sheet (step 3 preview)
        </h2>
        <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">
          How the printable, shareable certificate would look in this direction. Seeded example.
        </p>
        <article data-lattice="" className="mt-4 overflow-hidden rounded-panel border border-line bg-field shadow-overlay">
          <div className="p-6 sm:p-8">
            <div className="flex items-start justify-between gap-6">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-semibold text-ink-soft">
                  <LogoMark direction={direction} size={20} />
                  {PLACEHOLDER_NAME} · Certificate of authorship
                </p>
                <h3 className="mt-4 text-xl text-ink">{IDEA.current!.teaser.title}</h3>
                <p className="mt-1 text-ink-soft">Registered by Achieng Otieno, version 2</p>
              </div>
              <div className="hidden shrink-0 flex-col items-center gap-2 sm:flex">
                <QrCode matrix={qr} label={`Verify certificate ${CERT_ID}`} />
                <span className="text-xs text-ink-soft">Scan to verify</span>
              </div>
            </div>
            <dl className="mt-6 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
              <dt className="text-ink-soft">Certificate</dt>
              <dd className="font-semibold tracking-[0.06em] text-ink tabular-nums">{CERT_ID}</dd>
              <dt className="text-ink-soft">Registered</dt>
              <dd className="text-ink tabular-nums">{formatMoment(locale, IDEA.current!.registered_at!)}</dd>
              <dt className="text-ink-soft">Evidence</dt>
              <dd>
                <Badge tone="ok" icon={<CheckIcon />}>
                  Timestamped by an independent authority
                </Badge>
              </dd>
              <dt className="text-ink-soft">Fingerprint</dt>
              <dd>
                <Fingerprint hex={SHA256} className="text-sm leading-6" />
              </dd>
            </dl>
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-line bg-jacaranda-wash px-6 py-3 text-sm text-ink sm:px-8">
            <span>Anyone can check this record at /verify/{CERT_ID}</span>
            <LogoMark direction={direction} size={28} className="shrink-0" />
          </div>
        </article>
      </section>
    </SignedInShell>
  );
}
