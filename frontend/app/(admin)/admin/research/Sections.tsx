import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { formatConfidence, formatDate, formatMoment, safeHttpsUrl } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { CheckIcon, ClockIcon, ClosedIcon, CompaniesIcon, InfoIcon, PencilIcon } from "@/components/ui/icons";

import {
  nicheLabel,
  reviewHref,
  RUN_CHIP,
  runOutcome,
  type AdminNiche,
  type Candidate,
  type Excerpt,
  type NicheOption,
  type Run,
} from "./research";

// The research page's lists (REQ-RES-01): the cards waiting for review, the recent runs and the saved excerpts.

/**
 * One card waiting for review: its title (the way into the review), the start of its statement, its niche,
 * confidence, sources and draft date, and at most two tags (docs/spec/07 item 2): how it was drafted, and whether it
 * names an organisation (D-45).
 */
export async function CandidateRow({ candidate, niches }: { candidate: Candidate; niches: readonly AdminNiche[] }) {
  const t = await getTranslations("adminResearch");
  const locale = await getLocale();
  const confidence = formatConfidence(locale, candidate.confidence);
  const niche = nicheLabel(candidate.niche, niches);
  return (
    <li data-candidate={candidate.id} className="border-t border-line py-5 first:border-t-0 first:pt-0">
      <h3 className="text-lg text-ink">
        <Link
          href={reviewHref(candidate.id)}
          data-review-link=""
          className="inline-flex min-h-11 items-center font-semibold [overflow-wrap:anywhere] text-ink underline decoration-line decoration-1 underline-offset-4 hover:text-jacaranda hover:decoration-jacaranda"
        >
          {candidate.title}
        </Link>
      </h3>
      <p className="mt-1 line-clamp-2 max-w-[65ch] [overflow-wrap:anywhere] text-ink-soft">{candidate.statement}</p>
      <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
        <li data-chip="drafted" className="inline-flex items-center gap-1.5 font-semibold text-jacaranda">
          {candidate.seeded_example ? <InfoIcon className="size-4" /> : <PencilIcon className="size-4" />}
          {candidate.seeded_example ? t("queue.seeded") : t("queue.aiDrafted")}
        </li>
        {candidate.named_orgs.length > 0 ? (
          <li data-chip="orgs" className="inline-flex items-center gap-1.5 font-semibold text-ink">
            <CompaniesIcon className="size-4" />
            {t("queue.namesOrgs")}
          </li>
        ) : null}
        {niche ? <li>{niche}</li> : null}
        {confidence ? <li>{t("queue.confidence", { value: confidence })}</li> : null}
        <li>{t("queue.sources", { count: candidate.sources.length })}</li>
        <li>{t("queue.drafted", { date: formatMoment(locale, candidate.created_at) })}</li>
      </ul>
    </li>
  );
}

/** One run: niche, when it started, its status (mark, word, colour) and what came of it. */
export async function RunRow({ run, niches }: { run: Run; niches: readonly AdminNiche[] }) {
  const t = await getTranslations("adminResearch");
  const locale = await getLocale();
  const outcome = runOutcome(run);
  return (
    <li data-run={run.id} className="flex flex-col gap-1 border-t border-line py-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="font-semibold text-ink">{nicheLabel(run.niche, niches)}</span>
        <Chip kind={RUN_CHIP[run.status]}>{t(`runs.status.${run.status}`)}</Chip>
      </div>
      <p className="text-sm text-ink-soft">{t("runs.started", { date: formatMoment(locale, run.created_at) })}</p>
      <p className="max-w-[60ch] text-ink">
        {outcome.key === "cards"
          ? t("runs.cards", { count: outcome.count, total: outcome.total })
          : t(`runs.${outcome.key}`)}
      </p>
    </li>
  );
}

/** Freshness as a mark, a word and a colour (docs/spec/07 item 6: never colour alone). */
const FRESHNESS = {
  fresh: { tone: "text-ok", Icon: CheckIcon },
  stale: { tone: "text-ink", Icon: ClockIcon },
  archived: { tone: "text-ink-soft", Icon: ClosedIcon },
} as const;

/**
 * The saved excerpts a run reads (GET /api/admin/research/sources), by niche and folded away until opened: each with
 * its publisher, date, freshness today and topic, linked to where it was published.
 */
export async function SavedExcerpts({
  groups,
  asOf,
  total,
}: {
  groups: ReadonlyArray<NicheOption & { excerpts: Excerpt[] }>;
  asOf: string;
  total: number;
}) {
  const t = await getTranslations("adminResearch");
  const locale = await getLocale();
  return (
    <details className="group border-t border-line pt-6">
      <summary className="inline-flex min-h-11 cursor-pointer items-center gap-2 text-ink marker:content-none">
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          className="size-5 shrink-0 text-ink-soft transition-transform group-open:rotate-90 motion-reduce:transition-none"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m7.5 4.75 5.25 5.25-5.25 5.25" />
        </svg>
        <h2 className="text-lg text-ink">{t("sources.summary", { count: total })}</h2>
      </summary>
      <p className="mt-3 max-w-[60ch] text-ink-soft">{t("sources.lead", { date: formatDate(locale, asOf) })}</p>
      <div className="mt-6 flex flex-col gap-8">
        {groups.map((group) => (
          <section key={group.slug} aria-labelledby={`excerpts-${group.slug}`}>
            <h3 id={`excerpts-${group.slug}`} className="text-base font-semibold text-ink">
              {group.label}
            </h3>
            <ul className="mt-2 flex flex-col">
              {group.excerpts.map((excerpt) => (
                <li key={excerpt.id} className="flex flex-col gap-0.5 border-t border-line py-3 first:border-t-0">
                  <ExcerptLink url={excerpt.url}>{excerpt.topic}</ExcerptLink>
                  <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
                    <span>{excerpt.publisher}</span>
                    <span>{formatDate(locale, excerpt.published_date)}</span>
                    {excerpt.official ? <span>{t("sources.official")}</span> : null}
                    <FreshnessMark freshness={excerpt.freshness} label={t(`sources.${excerpt.freshness}`)} />
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </details>
  );
}

/** An excerpt's topic, linked to where it was published when the address is plain https. */
function ExcerptLink({ url, children }: { url: string; children: ReactNode }) {
  const href = safeHttpsUrl(url);
  if (!href) return <span className="font-medium text-ink">{children}</span>;
  return (
    <a
      href={href}
      rel="noopener noreferrer"
      className="inline-flex min-h-11 items-center self-start font-medium [overflow-wrap:anywhere] text-jacaranda underline decoration-1 hover:decoration-2"
    >
      {children}
    </a>
  );
}

function FreshnessMark({ freshness, label }: { freshness: Excerpt["freshness"]; label: string }) {
  const { tone, Icon } = FRESHNESS[freshness];
  return (
    <span data-freshness={freshness} className={`inline-flex items-center gap-1 font-semibold ${tone}`}>
      <Icon className="size-4 shrink-0" />
      {label}
    </span>
  );
}
