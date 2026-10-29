import { getLocale, getTranslations } from "next-intl/server";

import type { TrackerDetail } from "@/components/tracker/model";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { formatCalendarDate, formatDay } from "@/lib/format";

/**
 * The developer's view of an organisation's prior-knowledge declaration on their proposal (REQ-PROV-06; docs/spec/06
 * 6.4 pt 5: "shown to the owner"): who declared and when, the evidence's fingerprint (the full SHA-256, wrapped), its
 * title (the organisation's own words, as text) and its date, with the Help section that explains it. Server-rendered,
 * no client code; nothing on the organisation's own tracker (it reads its line under its buttons instead).
 */
export async function ReceivedDeclaration({ detail }: { detail: TrackerDetail }) {
  const pk = detail.my_party === "developer" ? detail.prior_knowledge : null;
  // Only a received declaration's shape is drawn: anything else (the organisation's window, by mistake) draws nothing.
  if (!pk || typeof pk.org_name !== "string" || typeof pk.evidence_sha256_hex !== "string") return null;
  const t = await getTranslations("tracker.declaration.received");
  const locale = await getLocale();
  return (
    <section
      aria-labelledby="declaration-heading"
      data-received-declaration=""
      className="mt-6 max-w-3xl rounded-panel border border-line bg-field p-5 sm:p-7"
    >
      <h2 id="declaration-heading" className="text-lg text-ink">
        {t("title", { org: pk.org_name, date: formatDay(locale, pk.declared_at) })}
      </h2>
      <p className="mt-2 max-w-[65ch] text-ink-soft">{t("lead", { org: pk.org_name })}</p>
      <dl className="mt-4 flex flex-col gap-3 sm:grid sm:grid-cols-[minmax(9rem,auto)_1fr] sm:gap-x-6">
        <dt className="text-sm text-ink-soft">{t("hash")}</dt>
        <dd data-hash="" className="font-mono text-sm break-all text-ink">
          {pk.evidence_sha256_hex}
        </dd>
        <dt className="text-sm text-ink-soft">{t("evidenceTitle")}</dt>
        <dd className="[overflow-wrap:anywhere] text-ink">{pk.evidence_title}</dd>
        <dt className="text-sm text-ink-soft">{t("evidenceDate")}</dt>
        <dd className="text-ink">{formatCalendarDate(locale, pk.evidence_dated_on)}</dd>
      </dl>
      <p className="mt-3">
        <StandaloneLink href="/help#confidential">{t("help")}</StandaloneLink>
      </p>
    </section>
  );
}
