import { useTranslations } from "next-intl";

import { whySourceOf, type Match } from "../../scout";

/**
 * The match's fit, 0 to 100: a short bar and the number (the bar is decoration; the words carry the meaning, and a
 * screen reader hears "Fit 82 out of 100"). `data-chip` counts it as one of the card's at most two chips.
 */
export function FitMeter({ score }: { score: number }) {
  const t = useTranslations("scoutMatches");
  const value = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <span data-chip="fit" className="inline-flex items-center gap-2 text-sm font-semibold text-jacaranda">
      <span aria-hidden="true" className="relative h-1.5 w-14 overflow-hidden rounded-full bg-line">
        <span className="absolute inset-y-0 left-0 rounded-full bg-jacaranda" style={{ width: `${value}%` }} />
      </span>
      <span aria-hidden="true" className="tabular-nums">
        {t("fit", { score: value })}
      </span>
      <span className="sr-only">{t("fitLong", { score: value })}</span>
    </span>
  );
}

/**
 * "Why this matches" as the scout wrote it, with who wrote it (the EM3 digest's labels): the model from the teaser,
 * the scout's rules, or the rules because the model answered with a demo fallback. The text is shown as text only.
 */
export function Why({ match, heading }: { match: Pick<Match, "why" | "why_source" | "demo_fallback">; heading?: boolean }) {
  const t = useTranslations("scoutMatches");
  if (!match.why) return null;
  const source = whySourceOf(match);
  return (
    <div className="max-w-[64ch] border-l-2 border-jacaranda pl-3" data-why-source={source}>
      {heading ? <h2 className="text-lg text-ink">{t("why")}</h2> : <p className="sr-only">{t("why")}</p>}
      <p className={heading ? "mt-1 text-ink [overflow-wrap:anywhere]" : "text-ink [overflow-wrap:anywhere]"}>
        {match.why}
      </p>
      <p className="mt-1 text-sm text-ink-soft">{t(`whySource.${source}`)}</p>
    </div>
  );
}
