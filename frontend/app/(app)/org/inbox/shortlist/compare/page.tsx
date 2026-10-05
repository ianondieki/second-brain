import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

import { orgContext } from "../../../data";
import { OrgRefusal } from "../../../OrgRefusal";
import { getCounties } from "../../../scout-data";
import { COMPARE_MAX, COMPARE_MIN, compareShows, parseCompareIds, shortlistHref } from "../../../shortlist";
import { getCompare } from "../../../shortlist-data";
import { CompareView } from "./CompareView";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("shortlist");
  return { title: t("compareTitle"), robots: { index: false } };
}

/**
 * Organisation › Inbox › Shortlist › Compare (REQ-REPO-02, P21 B4; D-57 (5)): 2 to 4 shortlisted proposals side by
 * side on their public teaser facts only (Tier 1), never their confidential detail, even after an Evaluation NDA: the
 * full proposal opens from each title, behind its NDA as usual. Asked for too few or too many, or for a proposal that
 * is not on the shortlist, the page says so in one sentence with the way back; a proposal no longer available is left
 * out, and the page says how many were.
 */
export default async function CompareScreen({ searchParams }: PageProps<"/org/inbox/shortlist/compare">) {
  const params = await searchParams;
  const { memberships, org, missing, query } = await orgContext(params.org);
  const t = await getTranslations("shortlist");
  const ti = await getTranslations("inbox");
  const nav = <OrgNav current="inbox" query={query} />;
  const back = org ? shortlistHref(memberships, org.org_id) : "/org/inbox/shortlist";
  const header = <PageHeader back={{ href: back, label: t("backToShortlist") }} title={t("compareTitle")} />;

  if (!org) {
    return (
      <SignedInShell homeHref={`/org${query}`} nav={nav}>
        {header}
        <div className="mt-6">
          {missing === "notMember" ? (
            <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
          ) : (
            <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
          )}
        </div>
      </SignedInShell>
    );
  }

  const asked = parseCompareIds(params.ids);
  const [read, counties] =
    asked.kind === "ok" ? await Promise.all([getCompare(org.org_id, asked.ids), getCounties()]) : [null, []];

  let body;
  if (!read) {
    body = (
      <EmptyState sentence={t("refusal.count", { min: COMPARE_MIN, max: COMPARE_MAX })} action={t("backToShortlist")} href={back} />
    );
  } else if (read.kind === "refused") {
    body = <OrgRefusal refusal={read.refusal} orgName={org.org_name} back={{ href: back, action: t("backToShortlist") }} />;
  } else if (read.kind === "problem") {
    body = (
      <EmptyState
        sentence={t(`refusal.${read.problem}`, { min: COMPARE_MIN, max: COMPARE_MAX })}
        action={t("backToShortlist")}
        href={back}
      />
    );
  } else if (compareShows(read.value.items.length) === "none") {
    body = <EmptyState sentence={t("noneAvailable")} action={t("backToShortlist")} href={back} />;
  } else if (compareShows(read.value.items.length) === "count") {
    // Only one of those asked is still available: nothing to compare it with.
    body = (
      <EmptyState sentence={t("refusal.count", { min: COMPARE_MIN, max: COMPARE_MAX })} action={t("backToShortlist")} href={back} />
    );
  } else {
    const left = asked.ids.length - read.value.items.length;
    body = (
      <>
        {left > 0 ? (
          <Callout tone="neutral" className="mb-8 max-w-[62ch]" data-left-out={left}>
            <p>{t("leftOut", { count: left })}</p>
          </Callout>
        ) : null}
        <CompareView items={read.value.items} memberships={memberships} org={org} counties={counties} />
      </>
    );
  }

  return (
    <SignedInShell homeHref={`/org${query}`} nav={nav} wide>
      <div className="max-w-5xl">
        {header}
        <p className="mt-4 max-w-[62ch] text-sm text-ink-soft" data-tier1-note="">
          {t("tier1Note")}
        </p>
        <div className="mt-8">{body}</div>
      </div>
    </SignedInShell>
  );
}
