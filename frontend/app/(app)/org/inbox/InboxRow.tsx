import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import type { InboxItem } from "../data";
import { MATURITY_KEY } from "../labels";
import { formatDay } from "../format";
import { StageChip } from "../StageChip";

/**
 * One proposal in the Inbox, Tier 1 only (the teaser the API returns): the stage chip and when it was sent, the title
 * (a link to the proposal page; the chip links to the engagement's tracker), its niche, the summary, and how far along it is and what the developer asks for.
 * Nothing names another organisation it was sent to (AC-REPO-6/a).
 */
export function InboxRow({ item, href, trackerHref }: { item: InboxItem; href: string; trackerHref?: string }) {
  const t = useTranslations("inbox");
  const tp = useTranslations("orgProposal");
  const tf = useTranslations("ideaFields");
  const locale = useLocale();
  const { teaser } = item.proposal;
  return (
    <article className="flex min-w-0 flex-col gap-1.5 border-t border-line py-5" data-proposal={item.proposal.id}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <StageChip engagement={item.engagement} href={trackerHref} />
        <p className="text-sm text-ink-soft">
          <time dateTime={item.pitched_at}>{t("sent", { date: formatDay(locale, item.pitched_at) })}</time>
        </p>
      </div>
      <h2 className="text-lg leading-snug">
        <Link
          href={href}
          className={
            "-my-2 inline-flex min-h-11 items-center py-2 font-semibold [overflow-wrap:anywhere] text-ink " +
            "underline decoration-transparent decoration-1 underline-offset-[0.2em] hover:decoration-jacaranda"
          }
        >
          {teaser.title ?? t("untitled")}
        </Link>
      </h2>
      {teaser.niche ? <p className="text-sm text-ink-soft">{teaser.niche.label}</p> : null}
      {teaser.summary ? <p className="line-clamp-3 max-w-[64ch] text-ink">{teaser.summary}</p> : null}
      <dl className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("maturityLabel")}</dt>
          <dd className="font-medium text-ink">
            {teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : t("notStated")}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("askLabel")}</dt>
          <dd className="font-medium text-ink">{teaser.ask ? t(`ask.${teaser.ask}`) : t("notStated")}</dd>
        </div>
      </dl>
    </article>
  );
}
