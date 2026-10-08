import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { orgEngagements } from "@/components/tracker/data";
import { EngagementCard } from "@/components/engagements/EngagementCard";
import { awaitsMe, type Summary } from "@/components/tracker/model";
import { Section } from "@/components/ui/Section";

import { getTeaser, orgContext } from "../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { ENGAGEMENTS_PATH, inboxHref, type Membership } from "../membership";
import { OrgPicker } from "../OrgPicker";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Engagements (REQ-ENG-03; D-67): the organisation's engagements from GET /api/orgs/{org_id}/engagements
 * as cards (five-dot stage line, whose turn), those waiting on the organisation first ("Needs us"). Each card opens the
 * tracker. Members of several organisations
 * pick one (?org=); an organisation the person is not a member of is refused, never silently swapped.
 */
export default async function OrganisationEngagementsPage({ searchParams }: PageProps<"/org/engagements">) {
  const { memberships, org, missing, query } = await orgContext((await searchParams).org);
  const [t, ti, tp] = await Promise.all([getTranslations("tracker"), getTranslations("inbox"), getTranslations("portal")]);

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="engagements" query={query} />} wide>
      <div className="max-w-5xl">
        <PageHero eyebrow={tp("eyebrow.engagements")} title={t("title")} lead={org ? t("orgLead") : undefined} />
        {org ? (
          <Body memberships={memberships} org={org} query={query} />
        ) : (
          <div>
            {missing === "notMember" ? (
              <EmptyState sentence={t("notMember")} action={t("openOwn")} href={ENGAGEMENTS_PATH} />
            ) : (
              <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
            )}
          </div>
        )}
      </div>
    </SignedInShell>
  );
}

async function Body({ memberships, org, query }: { memberships: Membership[]; org: Membership; query: string }) {
  const t = await getTranslations("tracker");
  const read = await orgEngagements(org.org_id);
  let body;
  if (!read.ok) {
    body =
      read.refusal === "mfaSetup" ? (
        <EmptyState sentence={t("refused.mfaSetup")} action={t("turnOnMfa")} href="/settings/security" primary />
      ) : (
        <EmptyState sentence={t("refused.notFound")} action={t("emptyOrgAction")} href={inboxHref(memberships, org.org_id)} />
      );
  } else if (read.value.length === 0) {
    body = <EmptyState sentence={t("emptyOrg")} action={t("emptyOrgAction")} href={inboxHref(memberships, org.org_id)} />;
  } else {
    body = <EngagementGrid items={read.value} query={query} />;
  }
  return (
    <>
      {memberships.length > 1 ? (
        <div className="mb-6">
          <OrgPicker memberships={memberships} current={org.org_id} action={ENGAGEMENTS_PATH} />
        </div>
      ) : null}
      {body}
    </>
  );
}

/**
 * The organisation's engagements as cards (components/engagements/EngagementCard, as the developer's list): those
 * waiting on the organisation first, under "Needs us", then the rest under their own heading; with one group only, the
 * cards stand under the page's title, their titles a level up (no lone heading).
 */
async function EngagementGrid({ items, query }: { items: Summary[]; query: string }) {
  const t = await getTranslations("tracker");
  // Each proposal's niche, for its cards' photograph band (D-67), from its public teaser (Tier 1, read once per
  // proposal and cached per request); a teaser that cannot be read leaves its cards without a band.
  const ids = [...new Set(items.map((item) => item.proposal_id))];
  const teasers = await Promise.all(ids.map((id) => getTeaser(id).catch(() => null)));
  const nicheOf = new Map(ids.map((id, index) => [id, teasers[index]?.teaser.niche ?? null]));
  const waiting = items.filter((item) => awaitsMe(item, "org"));
  const rest = items.filter((item) => !awaitsMe(item, "org"));
  const groups = [
    { key: "needs", title: t("needsUs"), items: waiting },
    { key: "rest", title: t("others"), items: rest },
  ].filter((group) => group.items.length > 0);
  const grid = (list: Summary[], level: 2 | 3, group: string, label?: string) => (
    // As many 20 rem columns as fit, sharing the width, as the developer's list.
    <ul aria-label={label} data-group={label ? group : undefined} className="grid gap-4 sm:grid-cols-[repeat(auto-fit,minmax(20rem,1fr))]">
      {list.map((item) => (
        <li key={item.id} className="cv-auto flex min-w-0 [--cv-size:16rem] [&>article]:flex-1">
          <EngagementCard
            item={item}
            mine="org"
            headingLevel={level}
            href={`${ENGAGEMENTS_PATH}/${encodeURIComponent(item.id)}${query}`}
            niche={nicheOf.get(item.proposal_id) ?? null}
          />
        </li>
      ))}
    </ul>
  );
  if (groups.length === 1) return grid(groups[0].items, 2, groups[0].key, groups[0].title);
  return (
    <div className="flex flex-col gap-12 lg:gap-14">
      {groups.map((group) => (
        <Section key={group.key} title={group.title} headingId={`engagements-${group.key}`} data-group={group.key}>
          {grid(group.items, 3, group.key)}
        </Section>
      ))}
    </div>
  );
}
