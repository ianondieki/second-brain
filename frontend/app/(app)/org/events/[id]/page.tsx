import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { CancelEvent } from "@/components/events/CancelEvent";
import { EventDetails } from "@/components/events/EventDetails";
import { cancellable, EVENT_CHIP } from "@/components/events/status";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Chip } from "@/components/tracker/Chip";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";
import { formatDay } from "@/lib/format";

import { orgContext } from "../../data";
import { OrgRefusal } from "../../OrgRefusal";
import { StateNote } from "../../problems/Notes";
import { getOrgEvent } from "../data";
import { eventsHref, postsEvents } from "../events";

export async function generateMetadata({ params, searchParams }: PageProps<"/org/events/[id]">): Promise<Metadata> {
  const t = await getTranslations("orgEvents");
  const { org } = await orgContext((await searchParams).org);
  const read = org ? await getOrgEvent(org.org_id, (await params).id) : null;
  return { title: read?.kind === "ok" ? read.value.title : t("pageTitle") };
}

const STATE_TONE = { draft: "info", published: "info", rejected: "error", cancelled: "neutral" } as const;

/**
 * Organisation › Events › one event (REQ-DEV-02): its status and who sees it now, the details as developers will read
 * them, and "Cancel this event" (a secondary, confirmed step) for its editors while it is a draft or published. No
 * primary action. A draft is not edited here in this track: the note under the details says how to change one.
 */
export default async function OrgEventPage({ params, searchParams }: PageProps<"/org/events/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const { memberships, org, missing, query: orgQueryText } = await orgContext(query.org);
  const [t, ti, locale] = await Promise.all([getTranslations("orgEvents"), getTranslations("inbox"), getLocale()]);
  const back = org ? eventsHref(memberships, org.org_id) : "/org/events";

  const frame = (title: ReactNode, body: ReactNode, status?: ReactNode) => (
    <SignedInShell homeHref={`/org${orgQueryText}`} nav={<OrgNav current="events" query={orgQueryText} />} wide>
      <div className="max-w-3xl">
        <PageHeader back={{ href: back, label: t("back") }} title={title} titleId="event-title">
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

  const read = await getOrgEvent(org.org_id, id);
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

  const event = read.value;
  return frame(
    event.title,
    <>
      {/* Takes focus when Cancel is confirmed (the page reads again with the cancelled note; its trigger is gone). */}
      <StateNote state={event.status}>
        <Callout tone={STATE_TONE[event.status]} className="mt-6" data-state-note={event.status}>
          <p>{t(`stateNote.${event.status}`)}</p>
        </Callout>
      </StateNote>

      <div className="mt-8">
        <EventDetails event={event} />
      </div>

      {event.status === "draft" ? (
        <p className="mt-4 max-w-[62ch] text-sm text-ink-soft" data-edit-note="">
          {t("editNote")}
        </p>
      ) : null}

      {postsEvents(org) && cancellable(event.status) ? (
        <div className="mt-8">
          <ClientStrings strings={await clientStrings(["eventForm"])}>
            <CancelEvent target={{ kind: "org", orgId: org.org_id }} eventId={event.id} poster={org.org_name} />
          </ClientStrings>
        </div>
      ) : null}
    </>,
    <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
      <Chip kind={EVENT_CHIP[event.status]}>{t(`status.${event.status}`)}</Chip>
      <span className="text-sm text-ink-soft">{t("posted", { date: formatDay(locale, event.created_at) })}</span>
    </p>,
  );
}
