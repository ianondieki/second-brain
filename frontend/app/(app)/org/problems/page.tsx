import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { NicheBand } from "@/components/ui/NicheBand";
import { PageHero } from "@/components/ui/PageHero";

import { getBriefs } from "../brief-data";
import { briefHref, briefUpgrade, newBriefHref, planFull, postsBriefs, problemsHref } from "../briefs";
import { orgContext } from "../data";
import { CARD_BAND, ItemGrid } from "../ItemCard";
import { first, inboxHref } from "../membership";
import { OrgRefusal } from "../OrgRefusal";
import { getCounties, readOrgPlans } from "../scout-data";
import { BriefItem } from "./BriefItem";
import { PlanNotice } from "./PlanNotice";
import { PostedNote } from "./Notes";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("briefs");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Problems (REQ-DIR-05; docs/spec/07 item 1 "Problems (Problem Briefs)"): the organisation's Briefs,
 * newest first, each with its state, the proposals answering it and its deadline; what the plan allows. "Post a brief"
 * is the one primary action for the members who post (owners, admins, signatories, reviewers); with no Brief yet the
 * empty state carries it (one sentence, one action: docs/spec/07 item 4).
 */
export default async function ProblemsPage({ searchParams }: PageProps<"/org/problems">) {
  const params = await searchParams;
  const { memberships, org, missing, query } = await orgContext(params.org);
  const [t, ti, tp] = await Promise.all([getTranslations("briefs"), getTranslations("inbox"), getTranslations("portal")]);

  const frame = (body: ReactNode, action?: ReactNode) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="problems" query={query} />} wide>
      <div className="max-w-5xl">
        <PageHero
          eyebrow={tp("eyebrow.problems")}
          title={t("title")}
          lead={org ? t("lead", { org: org.org_name }) : undefined}
          action={action}
        />
        {body}
      </div>
    </SignedInShell>
  );

  if (!org) {
    return frame(
      <div>
        {missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        )}
      </div>,
    );
  }

  const cursor = first(params.cursor);
  const [list, counties, plans] = await Promise.all([
    getBriefs(org.org_id, cursor && cursor.length <= 2000 ? cursor : undefined),
    getCounties(),
    readOrgPlans(),
  ]);
  const self = problemsHref(memberships, org.org_id);
  if (list.kind === "staleCursor" || (list.kind === "ok" && cursor && list.value.items.length === 0)) {
    return frame(<EmptyState sentence={t("staleCursor")} action={t("newest")} href={self} />);
  }
  if (list.kind === "refused") {
    return frame(
      <div>
        <OrgRefusal refusal={list.refusal} orgName={org.org_name} back={{ href: inboxHref(memberships, org.org_id), action: t("openInbox") }} />
      </div>,
    );
  }

  const { items, plan, next_cursor: next } = list.value;
  const posts = postsBriefs(org);
  const full = planFull(plan);
  const newHref = newBriefHref(memberships, org.org_id);
  const countyName = (code: string | null) => (code ? (counties.find((c) => c.code === code)?.name ?? code) : null);

  if (items.length === 0 && !cursor) {
    return frame(
      <EmptyState
        sentence={posts ? t("empty", { org: org.org_name }) : t("emptyViewer", { org: org.org_name })}
        action={posts ? t("post") : t("openInbox")}
        href={posts ? newHref : inboxHref(memberships, org.org_id)}
        primary={posts}
        data-empty="briefs"
      />,
    );
  }

  return frame(
    <>
      {first(params.posted) === "1" ? <PostedNote text={t("posted")} /> : null}
      <PlanNotice
        plan={plan}
        next={full && plans ? briefUpgrade(plans, plan.plan) : null}
        plansUnknown={full && plans === null}
        orgId={org.org_id}
        here={self}
      />
      {/* The list's name as a hidden h2, so the Briefs' h3 titles follow the page's h1 in order (axe heading-order). */}
      <section aria-labelledby="briefs-list" className="mt-2">
        <h2 id="briefs-list" className="sr-only">
          {t("listLabel")}
        </h2>
        <ItemGrid data-briefs="">
          {items.map((brief) => (
            <li key={brief.id}>
              <BriefItem
                brief={brief}
                href={briefHref(memberships, org.org_id, brief.id)}
                county={countyName(brief.county_code)}
                band={<NicheBand niche={brief.niche?.slug} county={brief.county_code} sizes={CARD_BAND} />}
              />
            </li>
          ))}
        </ItemGrid>
      </section>
      {next ? (
        <p className="mt-6">
          <Link href={problemsHref(memberships, org.org_id, { cursor: next })} className={standaloneLinkClass}>
            {t("older")}
          </Link>
        </p>
      ) : null}
    </>,
    // With every open Brief in use the notice above the list (and its upgrade link) is the next step: no "Post a
    // Brief" leading to a page that only repeats it.
    posts && !full ? (
      <ButtonLink href={newHref} variant="primary">
        {t("post")}
      </ButtonLink>
    ) : undefined,
  );
}
