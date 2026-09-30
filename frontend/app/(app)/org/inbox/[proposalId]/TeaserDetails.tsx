import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Section } from "@/components/ui/Section";

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
  // Sections only (no outer spacing): the page places them in its own column with its own gaps.
  return (
    <>
      {sections.map(({ key, text }) =>
        text ? (
          <Section key={key} title={t(key)} headingId={`teaser-${key}`}>
            <p className="max-w-[64ch] whitespace-pre-line [overflow-wrap:anywhere] text-ink">{text}</p>
          </Section>
        ) : null,
      )}
      <Section title={t("details")} headingId="teaser-details">
        <DescriptionList>
          <Description label={t("maturityLabel")}>
            {teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : ti("notStated")}
          </Description>
          <Description label={t("askLabel")}>{teaser.ask ? ti(`ask.${teaser.ask}`) : ti("notStated")}</Description>
          <Description label={t("from")}>{card.owner_handle}</Description>
          <Description label={t("registered")}>
            <time dateTime={card.registered_at}>{formatDay(locale, card.registered_at)}</time>
          </Description>
          <Description label={t("certificate")}>
            <Link
              href={`/verify/${encodeURIComponent(card.cert_id)}`}
              className={cn(standaloneLinkClass, "-my-2.5")}
            >
              {t("certificateLink", { id: card.cert_id })}
            </Link>
          </Description>
        </DescriptionList>
      </Section>
    </>
  );
}
