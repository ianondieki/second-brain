import { useLocale, useTranslations } from "next-intl";

import { Section } from "@/components/ui/Section";

import type { TeaserCard } from "../../data";
import { MATURITY_KEY } from "../../labels";
import { formatDay } from "../../format";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

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
  // The facts first, as one flat strip under the title (what it is, what the developer wants, who and when, the
  // certificate), then the teaser's own words as plain reading sections. The page places them with its own gaps.
  const fact = "flex min-w-0 flex-col gap-0.5";
  const label = "text-sm text-ink-soft";
  const value = "font-semibold text-ink [overflow-wrap:anywhere]";
  return (
    <>
      <section aria-labelledby="teaser-details" data-teaser-facts="">
        <h2 id="teaser-details" className="sr-only">
          {t("details")}
        </h2>
        <dl className="grid max-w-3xl grid-cols-2 gap-x-6 gap-y-5 rounded-panel border border-line bg-field p-5 sm:grid-cols-3 sm:p-6">
          <div className={fact}>
            <dt className={label}>{t("maturityLabel")}</dt>
            <dd className={value}>{teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : ti("notStated")}</dd>
          </div>
          <div className={fact}>
            <dt className={label}>{t("askLabel")}</dt>
            <dd className={value}>{teaser.ask ? ti(`ask.${teaser.ask}`) : ti("notStated")}</dd>
          </div>
          <div className={fact}>
            <dt className={label}>{t("from")}</dt>
            <dd className={value}>{card.owner_handle}</dd>
          </div>
          <div className={fact}>
            <dt className={label}>{t("registered")}</dt>
            <dd className={value}>
              <time dateTime={card.registered_at} className="tabular-nums">
                {formatDay(locale, card.registered_at)}
              </time>
            </dd>
          </div>
          <div className={`${fact} col-span-2`}>
            <dt className={label}>{t("certificate")}</dt>
            <dd>
              <StandaloneLink href={`/verify/${encodeURIComponent(card.cert_id)}`} className="-my-2.5 [overflow-wrap:anywhere]">
                {t("certificateLink", { id: card.cert_id })}
              </StandaloneLink>
            </dd>
          </div>
        </dl>
      </section>
      {sections.map(({ key, text }) =>
        text ? (
          <Section key={key} title={t(key)} headingId={`teaser-${key}`} className="reading">
            <p className="max-w-[68ch] text-[1.0625rem] leading-[1.7] whitespace-pre-line [overflow-wrap:anywhere] text-ink lg:text-lg">{text}</p>
          </Section>
        ) : null,
      )}
    </>
  );
}
