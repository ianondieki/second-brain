import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { Chip } from "@/components/tracker/Chip";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Panel } from "@/components/ui/Panel";
import { RowList } from "@/components/ui/RowList";

import { EmptyState } from "@/components/ui/EmptyState";
import { inboxHref, type Membership } from "../../membership";
import { OrgPicker } from "../../OrgPicker";
import { OrgRefusal } from "../../OrgRefusal";
import { configuresScouts, matchHref, scoutHref, type Match, type Scout, type ScoutList } from "../../scout";
import { getMatches, getScouts } from "../../scout-data";
import { MatchRow } from "./MatchRow";

/**
 * Inbox › Scout matches (REQ-SCOUT-02; docs/spec/07 item 1): the organisation's Scout Agent in a few words, then the
 * proposals it found, newest first. Without a scout the tab is its empty state: set one up (owners and admins).
 */
export async function ScoutMatches({ memberships, org }: { memberships: Membership[]; org: Membership }) {
  const t = await getTranslations("scoutMatches");
  const ti = await getTranslations("inbox");
  const [scouts, matches] = await Promise.all([getScouts(org.org_id), getMatches(org.org_id)]);
  const refusal = scouts.kind === "refused" ? scouts.refusal : matches.kind === "refused" ? matches.refusal : null;

  return (
    <>
      <p className="mt-6 max-w-[62ch] text-ink-soft">{t("lead", { org: org.org_name })}</p>
      {memberships.length > 1 ? (
        <div className="mt-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox" keep={{ tab: "matches" }} />
        </div>
      ) : null}
      <div className="mt-8">
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
        <ul className="mt-3 flex flex-col gap-4">
          {list.items.map((scout) => (
            <li key={scout.id} data-scout={scout.id}>
              <ScoutSummary scout={scout} href={admin ? scoutHref(memberships, org.org_id, scout.id) : undefined} />
            </li>
          ))}
        </ul>
        {admin && room ? (
          <p className="mt-1">
            <Link href={scoutHref(memberships, org.org_id)} className={standaloneLinkClass}>
              {t("add")}
            </Link>
          </p>
        ) : null}
      </Panel>

      <div className="mt-10">
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
          <RowList aria-label={t("listLabel", { org: org.org_name })}>
            {matches.map((match) => (
              <MatchRow key={match.id} match={match} href={matchHref(memberships, org.org_id, match.id)} />
            ))}
          </RowList>
        )}
      </div>
    </>
  );
}

async function ScoutSummary({ scout, href }: { scout: Scout; href?: string }) {
  const t = await getTranslations("scoutMatches");
  // Each "Change the scout" link names its scout by what it looks for (several scouts, several links).
  const niches = new Intl.ListFormat(await getLocale(), { type: "conjunction" }).format(scout.niches.map((n) => n.label));
  return (
    <div className="flex flex-col gap-2">
      <DescriptionList dense>
        <Description label={t("looksFor")}>
          <ul>
            {scout.niches.map((niche) => (
              <li key={niche.id} className="[overflow-wrap:anywhere]">
                {niche.label}
              </li>
            ))}
          </ul>
        </Description>
        <Description label={t("runs")}>{t(`frequency.${scout.frequency}`)}</Description>
        <Description label={t("status")}>
          <Chip kind={scout.paused ? "onHold" : "current"}>{scout.paused ? t("paused") : t("active")}</Chip>
        </Description>
      </DescriptionList>
      {href ? (
        <p>
          <Link href={href} className={standaloneLinkClass} aria-label={t("changeNamed", { niches })}>
            {t("change")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
