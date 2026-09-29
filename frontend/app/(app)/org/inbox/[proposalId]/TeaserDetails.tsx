import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { standaloneLinkClass } from "@/components/ui/Button";

import type { TeaserCard } from "../../data";
import { MATURITY_KEY } from "../../labels";
import { formatDay } from "../../format";

/**
 * The public teaser (Tier 1): what every signed-in person may read. The developer appears by their pseudonymous
 * handle until the organisation approves to proceed (docs/spec/06 6.1); the certificate id links to its public
 * /verify record.
 */
export function TeaserDetails({ card }: { card: TeaserCard }) {
  const t = useTranslations("orgProposal");
  const ti = useTranslations("inbox");
  const tf = useTranslations("ideaFields");
  const locale = useLocale();
  const { teaser } = card;
  const sections = [
    { key: "problem", text: teaser.problem_statement },
    { key: "summary", text: teaser.summary },
    { key: "impact", text: teaser.impact_claims },
  ] as const;
  return (
    <>
      {sections.map(({ key, text }) =>
        text ? (
          <section key={key} className="mt-8" aria-labelledby={`teaser-${key}`}>
            <h2 id={`teaser-${key}`} className="text-lg text-ink">
              {t(key)}
            </h2>
            <p className="mt-2 max-w-[64ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">{text}</p>
          </section>
        ) : null,
      )}
      <section className="mt-8" aria-labelledby="teaser-details">
        <h2 id="teaser-details" className="text-lg text-ink">
          {t("details")}
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-[auto_1fr]">
          <Row label={t("maturityLabel")}>{teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : ti("notStated")}</Row>
          <Row label={t("askLabel")}>{teaser.ask ? ti(`ask.${teaser.ask}`) : ti("notStated")}</Row>
          <Row label={t("from")}>{card.owner_handle}</Row>
          <Row label={t("registered")}>
            <time dateTime={card.registered_at}>{formatDay(locale, card.registered_at)}</time>
          </Row>
          <Row label={t("certificate")}>
            <Link href={`/verify/${encodeURIComponent(card.cert_id)}`} className={standaloneLinkClass}>
              {t("certificateLink", { id: card.cert_id })}
            </Link>
          </Row>
        </dl>
      </section>
    </>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere] text-ink">{children}</dd>
    </div>
  );
}
