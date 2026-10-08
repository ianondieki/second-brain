import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { isUuid } from "@/app/(app)/org/membership";
import { StateNote } from "@/app/(app)/org/problems/Notes";
import { ClientStrings } from "@/components/ClientStrings";
import { CancelEvent } from "@/components/events/CancelEvent";
import { EventDetails } from "@/components/events/EventDetails";
import { EVENT_CHIP } from "@/components/events/status";
import { Chip } from "@/components/tracker/Chip";
import { BackLink } from "@/components/ui/BackLink";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { formatDay, formatMoment } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../../AdminShell";
import { PageStepUp } from "../../research/PageStepUp";
import { staffContext } from "../../staff";
import { stepUpStrings } from "../../strings";
import { getAdminEvent } from "../data";
import { EventDecision } from "../EventDecision";
import { ADMIN_EVENTS_PATH } from "../events";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminEvents");
  return { title: t("detailTitle") };
}

const ROLES = new Set(["admin", "moderator"]);
const STATE_TONE = { draft: "info", published: "info", rejected: "error", cancelled: "neutral" } as const;

/**
 * One event under review (REQ-DEV-02; D-60): its status and who sees it now, the details as developers will read them,
 * and for a draft the decision (Publish, the screen's one primary action, or Reject; both confirmed, behind the
 * step-up); "Cancel this event" for a published one. Staff admins and moderators.
 */
export default async function AdminEventPage({ params }: PageProps<"/admin/events/[id]">) {
  const { role } = await staffContext();
  const { id } = await params;
  const [t, to, locale] = await Promise.all([getTranslations("adminEvents"), getTranslations("orgEvents"), getLocale()]);
  const shell = (children: ReactNode) => (
    <AdminShell role={role} current={ROLES.has(role) ? "events" : undefined} wide>
      <div className="max-w-3xl">
        <BackLink href={ADMIN_EVENTS_PATH}>{t("back")}</BackLink>
        {children}
      </div>
    </AdminShell>
  );
  const empty = (sentence: string, action: string, href: string) =>
    shell(
      <>
        <PageHeader title={t("detailTitle")} focusable />
        <div className="mt-6">
          <EmptyState sentence={sentence} action={action} href={href} />
        </div>
      </>,
    );
  if (!ROLES.has(role)) return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (!isUuid(id)) return empty(t("gone"), t("goneAction"), ADMIN_EVENTS_PATH);

  const loaded = await getAdminEvent(id);
  if (loaded.kind === "forbidden") return empty(t("notAdmin"), t("notAdminAction"), "/admin");
  if (loaded.kind === "stepUp") {
    return shell(
      <>
        <PageHeader title={t("detailTitle")} focusable />
        <div className="mt-6">
          <ClientStrings strings={await stepUpStrings()}>
            <PageStepUp />
          </ClientStrings>
        </div>
      </>,
    );
  }
  const event = loaded.data;
  if (!event) return empty(t("gone"), t("goneAction"), ADMIN_EVENTS_PATH);

  const organiser = event.organiser ?? t("unlisted");
  const strings = { ...(await clientStrings(["adminEvents", "eventForm"])), ...(await stepUpStrings()) };
  return shell(
    <article aria-labelledby="event-title" className="flex flex-col gap-10">
      <PageHeader titleId="event-title" focusable title={event.title}>
        <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
          <Chip kind={EVENT_CHIP[event.status]}>{to(`status.${event.status}`)}</Chip>
          <span className="text-sm text-ink-soft">{to("posted", { date: formatDay(locale, event.created_at) })}</span>
          {event.decided_at ? <span className="text-sm text-ink-soft">{t("decided", { date: formatMoment(locale, event.decided_at) })}</span> : null}
        </p>
      </PageHeader>

      {/* Takes focus when a decision or a cancellation changes the status (the page reads again; the buttons are gone). */}
      <StateNote state={event.status}>
        <Callout tone={STATE_TONE[event.status]} data-state-note={event.status}>
          <p>{to(`stateNote.${event.status}`)}</p>
        </Callout>
      </StateNote>

      <EventDetails event={event} organiser={organiser} />

      {event.status === "draft" ? (
        // The decision is what the event needs from staff now: raised, as on a quiz set or a research card.
        <Section
          title={t("decision.heading")}
          headingId="decision"
          description={t("decision.lead")}
          className="decision-panel rounded-panel border bg-field p-5 sm:p-6"
        >
          <ClientStrings strings={strings}>
            <EventDecision eventId={event.id} seen={event.updated_at} />
          </ClientStrings>
        </Section>
      ) : null}

      {event.status === "published" ? (
        <div>
          <ClientStrings strings={strings}>
            <CancelEvent target={{ kind: "staff" }} eventId={event.id} poster={organiser} />
          </ClientStrings>
        </div>
      ) : null}
    </article>,
  );
}
