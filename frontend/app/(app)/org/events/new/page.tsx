import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { EventForm } from "@/components/events/EventForm";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { orgContext } from "../../data";
import { orgQuery } from "../../membership";
import { getCounties, getVerification } from "../../scout-data";
import { EVENTS_PATH, eventsHref, postsEvents } from "../events";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("orgEvents");
  return { title: t("newTitle") };
}

/**
 * Organisation › Events › Post an event (REQ-DEV-02; D-60): for the editors of a legally verified (E2) organisation;
 * anyone else reads one sentence and one way back. Posted, the event waits for staff and its own page opens.
 */
export default async function NewEventPage({ searchParams }: PageProps<"/org/events/new">) {
  const { memberships, org, missing, query } = await orgContext((await searchParams).org);
  const t = await getTranslations("orgEvents");
  const ti = await getTranslations("inbox");
  const back = org ? eventsHref(memberships, org.org_id) : EVENTS_PATH;

  const frame = (body: ReactNode, lead?: string) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="events" query={query} />} wide>
      <div className="max-w-3xl">
        <PageHeader back={{ href: back, label: t("back") }} title={t("newTitle")} lead={lead} />
        <div className="mt-8">{body}</div>
      </div>
    </SignedInShell>
  );

  if (!org) {
    return frame(
      missing === "notMember" ? (
        <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
      ) : (
        <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
      ),
    );
  }
  if (!postsEvents(org)) {
    return frame(<EmptyState sentence={t("notEditor", { org: org.org_name })} action={t("back")} href={back} />);
  }
  const [verification, counties] = await Promise.all([getVerification(org.org_id), getCounties()]);
  // Not read (null): the form, and the API's answer is worded there.
  if (verification !== null && verification !== "e2") {
    return frame(<EmptyState sentence={t("notVerified", { org: org.org_name })} action={t("back")} href={back} />);
  }

  return frame(
    <ClientStrings strings={await clientStrings(["eventForm"])}>
      <EventForm
        counties={counties.map((c) => ({ id: c.code, label: c.name }))}
        poster={org.org_name}
        target={{ kind: "org", orgId: org.org_id }}
        doneBase={EVENTS_PATH}
        doneQuery={orgQuery(memberships, org.org_id)}
        cancelHref={back}
      />
    </ClientStrings>,
    t("newLead"),
  );
}
