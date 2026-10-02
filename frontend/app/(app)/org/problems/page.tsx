import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import { getBriefs } from "../brief-data";
import { briefHref, newBriefHref, postsBriefs, problemsHref } from "../briefs";
import { orgContext } from "../data";
import { first, inboxHref } from "../membership";
import { OrgRefusal } from "../OrgRefusal";
import { getCounties } from "../scout-data";
import { BriefItem } from "./BriefItem";

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
  const t = await getTranslations("briefs");
  const ti = await getTranslations("inbox");

  const frame = (body: ReactNode, action?: ReactNode) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="problems" query={query} />} wide>
      <div className="max-w-3xl">
        <PageHeader
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
      <div className="mt-8">
        {missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        )}
      </div>,
    );
  }

  const cursor = first(params.cursor);
  const [list, counties] = await Promise.all([
    getBriefs(org.org_id, cursor && cursor.length <= 2000 ? cursor : undefined),
    getCounties(),
  ]);
  const self = problemsHref(memberships, org.org_id);
  if (list.kind === "staleCursor" || (list.kind === "ok" && cursor && list.value.items.length === 0)) {
    return frame(<EmptyState className="mt-8" sentence={t("staleCursor")} action={t("newest")} href={self} />);
  }
  if (list.kind === "refused") {
    return frame(
      <div className="mt-8">
        <OrgRefusal refusal={list.refusal} orgName={org.org_name} back={{ href: inboxHref(memberships, org.org_id), action: t("openInbox") }} />
      </div>,
    );
  }

  const { items, plan, next_cursor: next } = list.value;
  const posts = postsBriefs(org);
  const newHref = newBriefHref(memberships, org.org_id);
  const countyName = (code: string | null) => (code ? (counties.find((c) => c.code === code)?.name ?? code) : null);

  if (items.length === 0 && !cursor) {
    return frame(
      <EmptyState
        className="mt-8"
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
      {first(params.posted) === "1" ? (
        <Alert tone="ok" className="mt-6">
          <p data-posted="">{t("posted")}</p>
        </Alert>
      ) : null}
      <p className="mt-6 text-sm text-ink" data-plan-cap={plan.problem_briefs ?? "unlimited"}>
        {plan.problem_briefs === null ? t("capUnlimited") : t("cap", { used: plan.used, limit: plan.problem_briefs })}
      </p>
      {/* The list under its own h2: the brief cards' titles are h3s, so the heading order stays whole (axe heading-order). */}
      <Section title={t("listLabel")} headingId="briefs-heading" className="mt-6">
        <RowList cards data-briefs="">
          {items.map((brief) => (
            <BriefItem
              key={brief.id}
              brief={brief}
              href={briefHref(memberships, org.org_id, brief.id)}
              county={countyName(brief.county_code)}
            />
          ))}
        </RowList>
      </Section>
      {next ? (
        <p className="mt-6">
          <Link href={problemsHref(memberships, org.org_id, { cursor: next })} className={standaloneLinkClass}>
            {t("older")}
          </Link>
        </p>
      ) : null}
    </>,
    posts ? (
      <ButtonLink href={newHref} variant="primary">
        {t("post")}
      </ButtonLink>
    ) : undefined,
  );
}
