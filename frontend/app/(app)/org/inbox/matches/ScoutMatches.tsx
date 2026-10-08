import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { Chip } from "@/components/tracker/Chip";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { NicheBand } from "@/components/ui/NicheBand";

import { EmptyState } from "@/components/ui/EmptyState";
import { inboxHref, type Membership } from "../../membership";
import { OrgPicker } from "../../OrgPicker";
import { OrgRefusal } from "../../OrgRefusal";
import { configuresScouts, matchHref, scoutHref, type Match, type Scout, type ScoutList } from "../../scout";
import { getMatches, getScouts } from "../../scout-data";
import { CARD_BAND, ItemGrid } from "../../ItemCard";
import { MatchRow } from "./MatchRow";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

/**
 * Inbox › Scout matches (REQ-SCOUT-02; docs/spec/07 item 1): the organisation's Scout Agent in a few words, then the
 * proposals it found, newest first. Without a scout the tab is its empty state: set one up (owners and admins).
 */
export async function ScoutMatches({ memberships, org }: { memberships: Membership[]; org: Membership }) {
  const ti = await getTranslations("inbox");
  const [scouts, matches] = await Promise.all([getScouts(org.org_id), getMatches(org.org_id)]);
  const refusal = scouts.kind === "refused" ? scouts.refusal : matches.kind === "refused" ? matches.refusal : null;

  return (
    <>
      {memberships.length > 1 ? (
        <div className="mb-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox" keep={{ tab: "matches" }} />
        </div>
      ) : null}
      <div>
        {refusal ? (
          <OrgRefusal refusal={refusal} orgName={org.org_name} back={{ href: "/org", action: ti("emptyAction") }} />
        ) : scouts.kind === "ok" && matches.kind === "ok" ? (
          <Body list={scouts.value} matches={matches.value} memberships={memberships} org={org} />
        ) : null}
      </div>
    </>
  );
}

async function Body({
  list,
  matches,
  memberships,
  org,
}: {
  list: ScoutList;
  matches: Match[];
  memberships: Membership[];
  org: Membership;
}) {
  const t = await getTranslations("scoutMatches");
  const admin = configuresScouts(org);
  const sent = inboxHref(memberships, org.org_id);

  if (list.items.length === 0) {
    return admin ? (
      <EmptyState
        sentence={t("emptyNoScout", { org: org.org_name })}
        action={t("emptyNoScoutAction")}
        href={scoutHref(memberships, org.org_id)}
        primary
      />
    ) : (
      <EmptyState sentence={t("emptyNoScoutMember", { org: org.org_name })} action={t("seeSent")} href={sent} />
    );
  }

  const room = list.plan.scout_agents === null || list.items.length < list.plan.scout_agents;
  return (
    <>
      {/* The screen's one panel: the scout that brings these matches, and the way to change it. */}
      <Panel as="section" aria-labelledby="scout-heading">
        <h2 id="scout-heading" className="text-lg text-ink">
          {t("scoutTitle")}
        </h2>
        <ul className="mt-4 flex flex-col">
          {list.items.map((scout) => (
            <li key={scout.id} data-scout={scout.id} className="border-t border-line py-4 first:border-t-0 first:pt-0 last:pb-0">
              <ScoutSummary scout={scout} href={admin ? scoutHref(memberships, org.org_id, scout.id) : undefined} />
            </li>
          ))}
        </ul>
        {admin && room ? (
          <p className="mt-3">
            <StandaloneLink href={scoutHref(memberships, org.org_id)}>
              {t("add")}
            </StandaloneLink>
          </p>
        ) : null}
      </Panel>

      <div className="mt-12">
        {matches.length === 0 ? (
          admin ? (
            <EmptyState
              sentence={t("emptyNoMatches")}
              action={t("change")}
              href={scoutHref(memberships, org.org_id, list.items[0].id)}
            />
          ) : (
            <EmptyState sentence={t("emptyNoMatches")} action={t("seeSent")} href={sent} />
          )
        ) : (
          <section aria-labelledby="matches-heading">
            <h2 id="matches-heading" className="text-xl text-ink">
              {(await getTranslations("portal"))("inbox.matchesTitle")}
            </h2>
            <ItemGrid aria-label={t("listLabel", { org: org.org_name })} className="mt-4">
              {matches.map((match) => (
                <li key={match.id}>
                  <MatchRow
                    match={match}
                    href={matchHref(memberships, org.org_id, match.id)}
                    org={org}
                    band={<NicheBand niche={match.available ? match.niche?.slug : null} county={match.available ? match.teaser?.county_code : null} sizes={CARD_BAND} />}
                  />
                </li>
              ))}
            </ItemGrid>
          </section>
        )}
      </div>
    </>
  );
}

async function ScoutSummary({ scout, href }: { scout: Scout; href?: string }) {
  const t = await getTranslations("scoutMatches");
  // Each "Change the scout" link names its scout by what it looks for (several scouts, several links).
  const niches = new Intl.ListFormat(await getLocale(), { type: "conjunction" }).format(scout.niches.map((n) => n.label));
  const label = "text-sm text-ink-soft";
  // One line of facts, as the proposal page's: what it looks for (the widest), how often, whether it runs; the link ends
  // the row from 640 px.
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-8">
      <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="col-span-2 flex min-w-0 flex-col gap-0.5 sm:col-span-1">
          <dt className={label}>{t("looksFor")}</dt>
          <dd className="font-semibold text-ink">
            <ul>
              {scout.niches.map((niche) => (
                <li key={niche.id} className="[overflow-wrap:anywhere]">
                  {niche.label}
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className={label}>{t("runs")}</dt>
          <dd className="font-semibold text-ink">{t(`frequency.${scout.frequency}`)}</dd>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <dt className={label}>{t("status")}</dt>
          <dd>
            <Chip kind={scout.paused ? "onHold" : "current"}>{scout.paused ? t("paused") : t("active")}</Chip>
          </dd>
        </div>
      </dl>
      {href ? (
        <p className="shrink-0">
          <Link href={href} className={standaloneLinkClass} aria-label={t("changeNamed", { niches })}>
            {t("change")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
