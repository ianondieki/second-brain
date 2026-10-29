import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/Card";
import { Section } from "@/components/ui/Section";

import { whySourceOf, type Match } from "../../scout";
import { FitBar } from "./FitBar";

/** The match's fit, 0 to 100, in the Scout matches' words (FitBar draws it). */
export function FitMeter({ score }: { score: number }) {
  const t = useTranslations("scoutMatches");
  const value = Math.max(0, Math.min(100, Math.round(score)));
  return <FitBar value={value} short={t("fit", { score: value })} long={t("fitLong", { score: value })} />;
}

/**
 * "Why this matches" as the scout wrote it, with who wrote it (the EM3 digest's labels): the model from the teaser,
 * the scout's rules, or the rules because the model answered with a demo fallback. The text is shown as text only.
 * On the match's page (`heading`) it is a Section; in a row, its name is for screen readers only. No coloured rule:
 * the words and who wrote them carry it.
 */
export function Why({ match, heading }: { match: Pick<Match, "why" | "why_source" | "demo_fallback">; heading?: boolean }) {
  const t = useTranslations("scoutMatches");
  if (!match.why) return null;
  const source = whySourceOf(match);
  const body = (
    <>
      <p className="text-ink [overflow-wrap:anywhere]">{match.why}</p>
      <p className="mt-1 text-sm text-ink-soft">{t(`whySource.${source}`)}</p>
    </>
  );
  if (heading) {
    return (
      <Section title={t("why")} headingId="why-heading" className="max-w-[64ch]" data-why-source={source}>
        <Card variant="wash">{body}</Card>
      </Section>
    );
  }
  return (
    <div className="max-w-[64ch]" data-why-source={source}>
      <p className="sr-only">{t("why")}</p>
      {body}
    </div>
  );
}
