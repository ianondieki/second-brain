import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { first } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import type { EventOut } from "@/components/events/event-draft";
import { EVENT_CHIP } from "@/components/events/status";
import { eventDay } from "@/components/events/when";
import { Chip } from "@/components/tracker/Chip";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { DataCell, DataRow, DataTable, dataLinkClass } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { formatTime } from "@/lib/format";

import { AdminShell } from "../AdminShell";
import { StaffEyebrow } from "../StaffEyebrow";
import { QueueSurface } from "../QueueSurface";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { ViewTabs } from "../ViewTabs";
import { getAdminEvents } from "./data";
import { adminEventHref, EVENT_VIEWS, eventsView, eventsViewHref, queueOrder } from "./events";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminEvents");
  return { title: t("pageTitle") };
}

const ROLES = new Set(["admin", "moderator"]);

/**
 * Events (REQ-DEV-02, REQ-ADM-01; D-60; P22 card B default (1)): the events waiting for a decision, soonest first, with
 * their organiser and date; the published ones, and the closed ones (rejected or cancelled), under their own tabs. Staff admins and
 * moderators decide; "Post a platform event" is the staff admin's one primary action. A stale second factor asks for a
 * fresh code first.
 */
export default async function AdminEventsPage({ searchParams }: PageProps<"/admin/events">) {
  const { role } = await staffContext();
  const view = eventsView(first((await searchParams).view));
  const t = await getTranslations("adminEvents");
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current={ROLES.has(role) ? "events" : undefined} wide>
      <div className="flex max-w-5xl flex-col">
        <PageHero
          eyebrow={<StaffEyebrow section="events" />}
          title={t("title")}
          lead={t("lead")}
          focusable
          action={
            role === "admin" ? (
              <ButtonLink href="/admin/events/new" variant="primary">
                {t("post")}
              </ButtonLink>
            ) : undefined
          }
        />
        {children}
      </div>
    </AdminShell>
  );
  const notAllowed = () => shell(<EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href="/admin" />);
  if (!ROLES.has(role)) return notAllowed();

  const loaded = await getAdminEvents(view);
  if (loaded.kind === "forbidden") return notAllowed();
  if (loaded.kind === "stepUp") {
    return shell(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }

  const items = queueOrder(view, loaded.data);
  const tabs = EVENT_VIEWS.map((key) => ({ key, label: t(`tabs.${key}`), href: eventsViewHref(key) }));
  return shell(
    <div>
      <ViewTabs label={t("tabs.label")} tabs={tabs} current={view} />
      <div className="mt-6">
        {items.length > 0 ? (
          <QueueSurface raised={view === "draft"}>
            <DataTable
              aria-label={t(`tabs.${view}`)}
              columns={[t("columns.event"), t("columns.organiser"), t("columns.when"), t("columns.status")]}
            >
              {items.map((event) => (
                <EventQueueRow key={event.id} event={event} />
              ))}
            </DataTable>
          </QueueSurface>
        ) : (
          <EmptyState
            rule={false}
            sentence={t(`empty.${view}`)}
            action={view === "draft" ? t("emptyActionPublished") : t("emptyActionWaiting")}
            href={eventsViewHref(view === "draft" ? "published" : "draft")}
          />
        )}
      </div>
    </div>,
  );
}

/** One event, a row of the queue: its title (the way in), the organiser, when it starts (Nairobi), its status. */
async function EventQueueRow({ event }: { event: EventOut }) {
  const [t, to, locale] = await Promise.all([getTranslations("adminEvents"), getTranslations("orgEvents"), getLocale()]);
  return (
    <DataRow data-admin-event={event.id} data-status={event.status}>
      <DataCell head label={t("columns.event")} className="sm:w-[40%]">
        <Link href={adminEventHref(event.id)} className={dataLinkClass}>
          {event.title}
        </Link>
      </DataCell>
      <DataCell label={t("columns.organiser")}>{event.organiser ?? t("unlisted")}</DataCell>
      <DataCell label={t("columns.when")} figure nowrap>
        {to("when", { day: eventDay(locale, event.starts_at), time: formatTime(locale, event.starts_at) })}
      </DataCell>
      <DataCell label={t("columns.status")} nowrap>
        <Chip kind={EVENT_CHIP[event.status]}>{to(`status.${event.status}`)}</Chip>
      </DataCell>
    </DataRow>
  );
}
