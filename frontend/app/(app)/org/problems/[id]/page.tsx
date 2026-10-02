import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { problemHref } from "@/components/problem/problem";
import { SignedInShell } from "@/components/SignedInShell";
import { Chip } from "@/components/tracker/Chip";
import { Callout } from "@/components/ui/Callout";
import { Card } from "@/components/ui/Card";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { formatCalendarDate, formatDay } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getBrief } from "../../brief-data";
import { closable, postsBriefs, problemsHref, STATE_CHIP, type BriefState } from "../../briefs";
import { orgContext } from "../../data";
import { OrgRefusal } from "../../OrgRefusal";
import { getCounties } from "../../scout-data";
import { StateNote } from "../Notes";
import { CloseBrief } from "./CloseBrief";

export async function generateMetadata({ params, searchParams }: PageProps<"/org/problems/[id]">): Promise<Metadata> {
  const t = await getTranslations("briefs");
  const { org } = await orgContext((await searchParams).org);
  const read = org ? await getBrief(org.org_id, (await params).id) : null;
  return { title: read?.kind === "ok" ? read.value.title : t("pageTitle") };
}

/** The note under the title, by state: who sees the Brief now (a static Callout; the error tone when not approved). */
const STATE_TONE: Record<BriefState, "info" | "error" | "neutral"> = {
  in_review: "info",
  published: "info",
  rejected: "error",
  closed: "neutral",
};

/**
 * Organisation › Problems › one Brief (REQ-DIR-05): its state and who sees it now, the problem as developers read it
 * (statement, who is affected, niche, region, budget band, deadline, proposals answering it), and "Close this brief"
 * for the members who post while it is open. No primary action: closing is a secondary, confirmed step.
 */
export default async function BriefPage({ params, searchParams }: PageProps<"/org/problems/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const { memberships, org, missing, query: orgQueryText } = await orgContext(query.org);
  const t = await getTranslations("briefs");
  const ti = await getTranslations("inbox");
  const locale = await getLocale();
  const back = org ? problemsHref(memberships, org.org_id) : "/org/problems";

  const frame = (title: ReactNode, body: ReactNode, status?: ReactNode) => (
    <SignedInShell homeHref={`/org${orgQueryText}`} nav={<OrgNav current="problems" query={orgQueryText} />} wide>
      <div className="max-w-3xl">
        <PageHeader back={{ href: back, label: t("back") }} title={title}>
          {status}
        </PageHeader>
        {body}
      </div>
    </SignedInShell>
  );

  if (!org) {
    return frame(
      t("pageTitle"),
      <div className="mt-8">
        {missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        )}
      </div>,
    );
  }

  const [read, counties] = await Promise.all([getBrief(org.org_id, id), getCounties()]);
  if (read === null || read.kind === "refused") {
    return frame(
      t("pageTitle"),
      <div className="mt-8">
        {read ? (
          <OrgRefusal refusal={read.refusal} orgName={org.org_name} back={{ href: back, action: t("back") }} />
        ) : (
          <EmptyState sentence={t("notFound")} action={t("back")} href={back} />
        )}
      </div>,
    );
  }

  const brief = read.value;
  const county = brief.county_code ? (counties.find((c) => c.code === brief.county_code)?.name ?? brief.county_code) : null;
  const notGiven = <span className="text-ink-soft">{t("notGiven")}</span>;
  return frame(
    brief.title,
    <>
      {/* Takes focus when Close is confirmed (the page reads again with the closed note; its trigger is gone). */}
      <StateNote state={brief.state}>
        <Callout tone={STATE_TONE[brief.state]} className="mt-6" data-state-note={brief.state}>
          <p>{t(`stateNote.${brief.state}`, { org: org.org_name })}</p>
          {brief.state === "published" ? <StandaloneLink href={problemHref(brief.id)}>{t("asDevelopers")}</StandaloneLink> : null}
        </Callout>
      </StateNote>

      <Card as="section" variant="flat" aria-labelledby="brief-problem" className="mt-8">
        <h2 id="brief-problem" className="sr-only">
          {t("facts.statement")}
        </h2>
        <p className="max-w-[65ch] text-lg [overflow-wrap:anywhere] whitespace-pre-line text-ink" data-statement="">
          {brief.statement}
        </p>
        <DescriptionList className="mt-5 border-t border-line pt-5">
          <Description label={t("facts.affected")}>{brief.affected_group ?? notGiven}</Description>
          <Description label={t("facts.niche")}>{brief.niche?.label ?? notGiven}</Description>
          <Description label={t("facts.region")}>{county ?? t("anywhere")}</Description>
          <Description label={t("facts.budget")}>{brief.budget_band?.label ?? notGiven}</Description>
          <Description label={t("facts.deadline")}>
            {brief.deadline ? formatCalendarDate(locale, brief.deadline) : t("noDeadline")}
          </Description>
          <Description label={t("facts.proposals")}>
            <span data-proposals={brief.proposal_count}>{t("proposals", { count: brief.proposal_count })}</span>
          </Description>
        </DescriptionList>
      </Card>

      {postsBriefs(org) && closable(brief) ? (
        <div className="mt-8">
          <ClientStrings strings={await clientStrings(["briefForm"])}>
            <CloseBrief orgId={org.org_id} briefId={brief.id} orgName={org.org_name} />
          </ClientStrings>
        </div>
      ) : null}
    </>,
    <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
      <Chip kind={STATE_CHIP[brief.state]}>{t(`state.${brief.state}`)}</Chip>
      <span className="text-sm text-ink-soft">{t("postedOn", { date: formatDay(locale, brief.created_at) })}</span>
    </p>,
  );
}
