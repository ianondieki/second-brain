import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { first } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { PageHero } from "@/components/ui/PageHero";
import { DataTable } from "@/components/ui/DataTable";

import { formatDay } from "@/lib/format";

import { AdminShell } from "../AdminShell";
import { StaffEyebrow } from "../StaffEyebrow";
import { QueueSummary, QueueSurface } from "../QueueSurface";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { ViewTabs } from "../ViewTabs";
import { CaseRow } from "./CaseRow";
import { getQueue } from "./data";
import { caseHref, moderationView, viewHref, visibility, type Case } from "./moderation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminModeration");
  return { title: t("pageTitle") };
}

/** The staff roles the API admits to the moderation queue (bridge/admin/deps.py StaffModerator). */
const ROLES = new Set(["admin", "moderator"]);

/**
 * Moderation (REQ-MOD-01, REQ-ADM-01; docs/spec/06 6.12; M2 walkthrough step 6): the cases the pre-screen held or
 * queued, oldest first, and the decided ones, newest decision first. "Review the oldest case" (the oldest this
 * moderator can decide) is the screen's one primary action. Staff admins and moderators; a stale second factor asks for
 * a fresh code first.
 */
export default async function ModerationPage({ searchParams }: PageProps<"/admin/moderation">) {
  const { role } = await staffContext();
  const view = moderationView(first((await searchParams).view));
  const t = await getTranslations("adminModeration");
  // The header's action slot holds "Review the oldest case", the screen's one primary action, when there is one.
  const shell = (children: React.ReactNode, action?: React.ReactNode) => (
    <AdminShell role={role} current="moderation" wide>
      <div className="flex max-w-5xl flex-col gap-8">
        <PageHero eyebrow={<StaffEyebrow section="moderation" />} title={t("title")} lead={t("lead")} focusable action={action} />
        {children}
      </div>
    </AdminShell>
  );
  const notAllowed = () =>
    shell(<EmptyState sentence={t("notAllowed")} action={t("notAllowedAction")} href="/admin" />);
  if (!ROLES.has(role)) return notAllowed();

  const loaded = await getQueue(view);
  if (loaded.kind === "forbidden") return notAllowed();
  if (loaded.kind === "stepUp") {
    return shell(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }

  const items = loaded.data;
  const oldest = view === "open" ? items.find((item) => item.actions.length > 0) : undefined;
  const tabs = [
    { key: "open", label: t("tabs.open"), href: viewHref("open") },
    { key: "decided", label: t("tabs.decided"), href: viewHref("decided") },
  ];
  return shell(
    <div>
      <ViewTabs label={t("tabsLabel")} tabs={tabs} current={view} />
      <div className="mt-6">
        {items.length > 0 ? (
          <QueueSurface raised={view === "open"} summary={view === "open" ? await openSummary(items) : undefined}>
            <DataTable
              aria-label={view === "open" ? t("listOpen") : t("listDecided")}
              columns={[t("columns.case"), t("columns.kind"), t("columns.when"), t("columns.status")]}
            >
              {items.map((item) => (
                <CaseRow key={item.id} item={item} />
              ))}
            </DataTable>
          </QueueSurface>
        ) : view === "open" ? (
          <EmptyState rule={false} sentence={t("emptyOpen")} action={t("emptyOpenAction")} href={viewHref("decided")} />
        ) : (
          <EmptyState rule={false} sentence={t("emptyDecided")} action={t("emptyDecidedAction")} href={viewHref("open")} />
        )}
      </div>
    </div>,
    oldest ? (
      <ButtonLink href={caseHref(oldest.id)} variant="primary">
        {t("reviewOldest")}
      </ButtonLink>
    ) : undefined,
  );
}

/**
 * The open queue at a glance: how many cases, how many keep their subject hidden while they wait (the ones that cost
 * an author most), and the day the oldest was filed (the queue is oldest first).
 */
async function openSummary(items: readonly Case[]) {
  const t = await getTranslations("adminModeration");
  const locale = await getLocale();
  const hidden = items.filter((item) => {
    const seen = visibility(item);
    return seen === "hidden" || seen === "briefHidden";
  }).length;
  const oldest = items.reduce((first, item) => (item.created_at < first ? item.created_at : first), items[0].created_at);
  return (
    <QueueSummary
      figures={[
        { key: "open", label: t("summary.open"), value: items.length },
        { key: "hidden", label: t("summary.hidden"), value: hidden },
        { key: "oldest", label: t("summary.oldest"), value: formatDay(locale, oldest) },
      ]}
    />
  );
}
