import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";

import { orgContext } from "../data";
import { inboxHref } from "../membership";
import { OrgRefusal } from "../OrgRefusal";
import { getVerification } from "../scout-data";
import { getOrgEvents } from "./data";
import { EventItem } from "./EventItem";
import { newEventHref, orgEventHref, postsEvents } from "./events";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("orgEvents");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Events (REQ-DEV-02; D-60; P22 card B default (6), the portal's fifth section): the organisation's
 * events, newest first, each with when, where and its status. "Post an event" is the one primary action for its
 * editors (owners, admins, signatories, reviewers) of a legally verified (E2) organisation; anyone else reads the
 * sentence that says who posts. With no event yet the empty state says it (one sentence, one action: spec 07 item 4).
 */
export default async function EventsPage({ searchParams }: PageProps<"/org/events">) {
  const { memberships, org, missing, query } = await orgContext((await searchParams).org);
  const t = await getTranslations("orgEvents");
  const ti = await getTranslations("inbox");

  const frame = (body: ReactNode, action?: ReactNode, lead?: string) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="events" query={query} />} wide>
      <div className="max-w-3xl">
        <PageHeader title={t("title")} lead={lead} action={action} />
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

  const [list, verification] = await Promise.all([getOrgEvents(org.org_id), getVerification(org.org_id)]);
  const lead = t("lead", { org: org.org_name });
  if (list.kind === "refused") {
    return frame(
      <div className="mt-8">
        <OrgRefusal refusal={list.refusal} orgName={org.org_name} back={{ href: inboxHref(memberships, org.org_id), action: t("home") }} />
      </div>,
      undefined,
      lead,
    );
  }

  const editor = postsEvents(org);
  // Only a legally verified organisation posts (403 verification_required otherwise); not read (null): offered, and
  // the form words the API's answer.
  const verified = verification === null || verification === "e2";
  const posts = editor && verified;
  const newHref = newEventHref(memberships, org.org_id);
  // Who may not post reads why, in one sentence (the Briefs' wording).
  const why = !editor ? t("notEditor", { org: org.org_name }) : !verified ? t("notVerified", { org: org.org_name }) : null;

  if (list.value.length === 0) {
    return frame(
      <EmptyState
        className="mt-8"
        sentence={posts ? t("empty", { org: org.org_name }) : editor ? (why ?? "") : t("emptyViewer", { org: org.org_name })}
        action={posts ? t("post") : t("home")}
        href={posts ? newHref : `/org${query}`}
        primary={posts}
        data-empty="events"
      />,
      undefined,
      lead,
    );
  }

  return frame(
    <>
      {why ? (
        <p className="mt-4 max-w-[62ch] text-sm text-ink-soft" data-events-why="">
          {why}
        </p>
      ) : null}
      {/* The list's name as a hidden h2, so the events' h3 titles follow the page's h1 in order (axe heading-order). */}
      <section aria-labelledby="events-list" className="mt-8">
        <h2 id="events-list" className="sr-only">
          {t("listLabel")}
        </h2>
        <RowList cards data-org-events="">
          {list.value.map((event) => (
            <EventItem key={event.id} event={event} href={orgEventHref(memberships, org.org_id, event.id)} />
          ))}
        </RowList>
      </section>
    </>,
    posts ? (
      <ButtonLink href={newHref} variant="primary">
        {t("post")}
      </ButtonLink>
    ) : undefined,
    lead,
  );
}
