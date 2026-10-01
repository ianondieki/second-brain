import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { formatConfidence, formatDate, formatMoment, safeHttpsUrl } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { Badge } from "@/components/ui/Badge";
import { CheckIcon, ClockIcon, ClosedIcon, CompaniesIcon, InfoIcon, PencilIcon } from "@/components/ui/icons";
import Link from "next/link";

import { DataCell, DataRow, dataLinkClass } from "@/components/ui/DataTable";

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
 * One card waiting for review, a row of the queue's table: its title (the way into the review, the row header) with
 * at most two badges under it (docs/spec/07 item 2: how it was drafted, and whether it names an organisation, D-45),
 * then its niche, confidence, sources and draft date. `data-review-link` marks the title's link (its own 44 px band).
 */
export async function CandidateRow({ candidate, niches }: { candidate: Candidate; niches: readonly AdminNiche[] }) {
  const t = await getTranslations("adminResearch");
  const locale = await getLocale();
  const confidence = formatConfidence(locale, candidate.confidence);
  const niche = nicheLabel(candidate.niche, niches);
  return (
    <DataRow data-candidate={candidate.id}>
      <DataCell head label={t("columns.card")} className="sm:w-[44%]">
        <Link href={reviewHref(candidate.id)} data-review-link="" className={dataLinkClass}>
          {candidate.title}
        </Link>
        <p className="mt-1 line-clamp-2 max-w-[52ch] text-sm [overflow-wrap:anywhere] text-ink-soft">{candidate.statement}</p>
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          <Badge data-chip="drafted" tone="accent" icon={candidate.seeded_example ? <InfoIcon /> : <PencilIcon />}>
            {candidate.seeded_example ? t("queue.seeded") : t("queue.aiDrafted")}
          </Badge>
          {candidate.named_orgs.length > 0 ? (
            <Badge data-chip="orgs" tone="neutral" icon={<CompaniesIcon />}>
              {t("queue.namesOrgs")}
            </Badge>
          ) : null}
        </p>
      </DataCell>
      <DataCell label={t("columns.niche")}>{niche ?? "–"}</DataCell>
      <DataCell label={t("columns.confidence")} figure nowrap>
        {confidence ?? "–"}
      </DataCell>
      <DataCell label={t("columns.sources")} figure nowrap>
        {candidate.sources.length}
      </DataCell>
      <DataCell label={t("columns.drafted")} figure nowrap className="text-ink-soft">
        {formatMoment(locale, candidate.created_at)}
      </DataCell>
    </DataRow>
  );
}

/** One run, a row: its niche, when it started, its status (mark, word, colour) and what came of it. */
export async function RunRow({ run, niches }: { run: Run; niches: readonly AdminNiche[] }) {
  const t = await getTranslations("adminResearch");
  const locale = await getLocale();
  const outcome = runOutcome(run);
  return (
    <DataRow data-run={run.id}>
      <DataCell head label={t("columns.niche")} className="font-semibold sm:w-[30%]">
        {nicheLabel(run.niche, niches)}
      </DataCell>
      <DataCell label={t("columns.started")} figure nowrap className="text-ink-soft">
        {formatMoment(locale, run.created_at)}
      </DataCell>
      <DataCell label={t("columns.status")} nowrap>
        <Chip kind={RUN_CHIP[run.status]}>{t(`runs.status.${run.status}`)}</Chip>
      </DataCell>
      <DataCell label={t("columns.result")}>
        {outcome.key === "cards" ? t("runs.cards", { count: outcome.count, total: outcome.total }) : t(`runs.${outcome.key}`)}
      </DataCell>
    </DataRow>
  );
}

/** Freshness as a Badge: a mark, a word and a tone (docs/spec/07 item 6: never colour alone). */
const FRESHNESS = {
  fresh: { tone: "ok", Icon: CheckIcon },
  stale: { tone: "neutral", Icon: ClockIcon },
  archived: { tone: "neutral", Icon: ClosedIcon },
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
    <details className="group">
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
      className="inline-flex min-h-11 items-center self-start font-medium [overflow-wrap:anywhere] text-accent underline decoration-1 hover:decoration-2"
    >
      {children}
    </a>
  );
}

function FreshnessMark({ freshness, label }: { freshness: Excerpt["freshness"]; label: string }) {
  const { tone, Icon } = FRESHNESS[freshness];
  return (
    <Badge data-freshness={freshness} tone={tone} icon={<Icon />}>
      {label}
    </Badge>
  );
}
