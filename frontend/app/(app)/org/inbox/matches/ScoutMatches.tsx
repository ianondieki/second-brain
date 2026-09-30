import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Chip } from "@/components/tracker/Chip";
import { standaloneLinkClass } from "@/components/ui/Button";

import { EmptyState } from "../../EmptyState";
import { inboxHref, type Membership } from "../../membership";
import { OrgPicker } from "../../OrgPicker";
import { ACTION_HREF, type Refusal } from "../../refusals";
import { configuresScouts, matchHref, scoutHref, type Match, type Scout, type ScoutList } from "../../scout";
import { getMatches, getScouts } from "../../scout-data";
import { MatchRow } from "./MatchRow";

/**
 * Inbox › Scout matches (REQ-SCOUT-02; docs/spec/07 item 1): the organisation's Scout Agent in a few words, then the
 * proposals it found, newest first. Without a scout the tab is its empty state: set one up (owners and admins).
 */
export async function ScoutMatches({ memberships, org }: { memberships: Membership[]; org: Membership }) {
  const t = await getTranslations("scoutMatches");
  const [scouts, matches] = await Promise.all([getScouts(org.org_id), getMatches(org.org_id)]);
  const refusal = scouts.kind === "refused" ? scouts.refusal : matches.kind === "refused" ? matches.refusal : null;

  return (
    <>
      <p className="mt-6 max-w-[62ch] text-ink-soft">{t("lead", { org: org.org_name })}</p>
      {memberships.length > 1 ? (
        <div className="mt-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox" />
        </div>
      ) : null}
      <div className="mt-8">
        {refusal ? (
          <Refused refusal={refusal} org={org} />
        ) : scouts.kind === "ok" && matches.kind === "ok" ? (
          <Body list={scouts.value} matches={matches.value} memberships={memberships} org={org} />
        ) : null}
      </div>
    </>
  );
}

async function Refused({ refusal, org }: { refusal: Refusal; org: Membership }) {
  const t = await getTranslations("inbox");
  const tp = await getTranslations("orgProposal");
  if (refusal === "mfa_enrolment_required") {
    return (
      <EmptyState
        sentence={t("refusedMfaSetup", { org: org.org_name })}
        action={tp("action.turnOnMfa")}
        href={ACTION_HREF.turnOnMfa!}
        primary
      />
    );
  }
  if (refusal === "mfa_required") {
    return (
      <EmptyState sentence={t("refusedMfaCode")} action={tp("action.enterCode")} href={ACTION_HREF.enterCode!} primary />
    );
  }
  return <EmptyState sentence={t("refusedNotFound")} action={t("emptyAction")} href="/org" />;
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
      <section aria-labelledby="scout-heading" className="rounded-panel border border-line bg-field px-4 py-4 sm:px-5">
        <h2 id="scout-heading" className="text-lg text-ink">
          {t("scoutTitle")}
        </h2>
        <ul className="mt-1 flex flex-col">
          {list.items.map((scout) => (
            <li key={scout.id} className="border-t border-line pt-3 first:border-t-0 first:pt-1" data-scout={scout.id}>
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
      </section>

      <div className="mt-8">
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
          <section aria-label={t("listLabel", { org: org.org_name })}>
            {matches.map((match) => (
              <MatchRow key={match.id} match={match} href={matchHref(memberships, org.org_id, match.id)} />
            ))}
          </section>
        )}
      </div>
    </>
  );
}

async function ScoutSummary({ scout, href }: { scout: Scout; href?: string }) {
  const t = await getTranslations("scoutMatches");
  return (
    <div className="flex flex-col gap-2 pb-2">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-ink-soft">{t("looksFor")}</dt>
        <dd className="min-w-0 text-ink">
          <ul>
            {scout.niches.map((niche) => (
              <li key={niche.id} className="[overflow-wrap:anywhere]">
                {niche.label}
              </li>
            ))}
          </ul>
        </dd>
        <dt className="text-ink-soft">{t("runs")}</dt>
        <dd className="text-ink">{t(`frequency.${scout.frequency}`)}</dd>
        <dt className="text-ink-soft">{t("status")}</dt>
        <dd>
          <Chip kind={scout.paused ? "onHold" : "current"}>{scout.paused ? t("paused") : t("active")}</Chip>
        </dd>
      </dl>
      {href ? (
        <p>
          <Link href={href} className={standaloneLinkClass}>
            {t("change")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
